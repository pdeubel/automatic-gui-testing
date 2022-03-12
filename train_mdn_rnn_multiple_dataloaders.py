import logging
import os
import random
from typing import Optional, List

import click
# noinspection PyUnresolvedReferences
import comet_ml  # Needs to be imported __before__ torch
import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm

from data.dataset_implementations import get_main_rnn_data_loader, get_individual_rnn_data_loaders
from evaluation.mdn_rnn.reward_comparison import compare_reward_of_m_model_to_sequence
from models import select_rnn_model
from models.rnn import BaseRNN
from utils.data_processing_utils import preprocess_observations_with_vae, get_vae_preprocessed_data_path_name
from utils.logging.improved_summary_writer import ImprovedSummaryWriter
from utils.setup_utils import initialize_logger, load_yaml_config, set_seeds, get_device, save_yaml_config, pretty_json
from utils.training_utils import load_vae_architecture, save_checkpoint
from utils.training_utils.average_meter import AverageMeter
from utils.training_utils.training_utils import (
    generate_initial_observation_latent_vector, get_rnn_action_transformation_function,
    get_rnn_reward_transformation_function
)


# from utils.misc import ASIZE, LSIZE, RSIZE, RED_SIZE, SIZE
# from utils.learning import EarlyStopping
## WARNING : THIS SHOULD BE REPLACED WITH PYTORCH 0.5
# from utils.learning import ReduceLROnPlateau


def data_pass(model: BaseRNN, vae, summary_writer: Optional[ImprovedSummaryWriter], optimizer,
              data_loaders: List[DataLoader],
              device: torch.device, tbptt_frequency: int, current_epoch: int, global_log_step: int,
              scalar_log_frequency: int, train: bool, debug: bool):
    if train:
        model.train()
        loss_key = "loss"
        latent_loss_key = "latent_loss"
        reward_loss_key = "reward_loss"

        # During training, we don't want to have the same order of sequences in each epoch, therefore shuffle the
        # data_loaders list, which contains a DataLoader object per sequence
        random.shuffle(data_loaders)
    else:
        model.eval()
        loss_key = "val_loss"
        latent_loss_key = "val_latent_loss"
        reward_loss_key = "val_reward_loss"

    total_loss_meter = AverageMeter(loss_key, ":.4f")
    latent_loss_meter = AverageMeter(latent_loss_key, ":.4f")
    reward_loss_meter = AverageMeter(reward_loss_key, ":.4f")

    progress_bar = tqdm(total=sum([len(x) for x in data_loaders]), unit="batch", desc=f"Epoch {current_epoch}")
    log_step = 0

    # Each DataLoader in data_loaders resembles one sequence of interactions that was recorded on the actual env
    # The order of the sequences might be shuffled, but going through one sequence itself is done sequentially
    for sequence_idx, sequence_data_loader in enumerate(data_loaders):
        model.initialize_hidden()
        optimizer.zero_grad()

        for data_idx, data in enumerate(sequence_data_loader):
            mus, next_mus, log_vars, next_log_vars, rewards, actions = [d.to(device) for d in data]

            batch_size = mus.size(0)
            latent_obs = vae.reparameterize(mus, log_vars)
            latent_next_obs = vae.reparameterize(next_mus, next_log_vars)

            if train:
                model_output = model(latent_obs, actions)
                loss, (latent_loss, reward_loss) = model.loss_function(
                    next_latent_vector=latent_next_obs,
                    reward=rewards,
                    model_output=model_output
                )

                # Store gradients only for tbptt_frequency * sequence_length (rnn parameter) time steps
                if (data_idx + 1) % tbptt_frequency == 0 or data_idx == (len(sequence_data_loader) - 1):
                    loss.backward()
                    optimizer.step()
                    optimizer.zero_grad()
                    model.hidden = (model.hidden[0].detach(), model.hidden[1].detach())
                else:
                    loss.backward(retain_graph=True)
            else:
                with torch.no_grad():
                    # Do not need to detach here, as we don't compute gradients anyway
                    model_output = model(latent_obs, actions)
                    loss, (latent_loss, reward_loss) = model.loss_function(next_latent_vector=latent_next_obs,
                                                                           reward=rewards, model_output=model_output)

            total_loss_meter.update(loss.item(), batch_size)
            latent_loss_meter.update(latent_loss, batch_size)
            reward_loss_meter.update(reward_loss, batch_size)

            if (log_step % scalar_log_frequency == 0
                    or (sequence_idx == (len(data_loaders) - 1) and log_step == (len(sequence_data_loader) - 1))):
                progress_bar.set_postfix_str(f"loss={total_loss_meter.avg:.4f} latent={latent_loss_meter.avg:.4f} "
                                             f"reward={reward_loss_meter.avg:.4f}")

                if not debug:
                    summary_writer.add_scalar(loss_key, total_loss_meter.avg, global_step=global_log_step)
                    summary_writer.add_scalar(latent_loss_key, latent_loss_meter.avg, global_step=global_log_step)
                    summary_writer.add_scalar(reward_loss_key, reward_loss_meter.avg, global_step=global_log_step)

            progress_bar.update(1)
            log_step += 1
            global_log_step += 1

    progress_bar.close()

    if not debug:
        summary_writer.add_scalar(f"epoch_{loss_key}", total_loss_meter.avg, global_step=current_epoch)

    return total_loss_meter.avg, global_log_step


@click.command()
@click.option("-c", "--config", "config_path", type=str, required=True,
              help="Path to a YAML configuration containing training options")
@click.option("--disable-comet/--no-disable-comet", type=bool, default=False,
              help="Disable logging to Comet (automatically disabled when API key is not provided in home folder)")
def main(config_path: str, disable_comet: bool):
    logger, _ = initialize_logger()
    logger.setLevel(logging.INFO)

    config = load_yaml_config(config_path)

    batch_size = config["experiment_parameters"]["batch_size"]
    sequence_length = config["experiment_parameters"]["sequence_length"]
    learning_rate = config["experiment_parameters"]["learning_rate"]
    max_epochs = config["experiment_parameters"]["max_epochs"]
    tbptt_frequency = config["experiment_parameters"]["tbptt_frequency"]

    assert tbptt_frequency > 0, ("Truncated backpropagation through time frequency (tbptt_frequency) must be "
                                 "higher than 0")

    dataset_name = config["experiment_parameters"]["dataset"]
    dataset_path = config["experiment_parameters"]["data_path"]
    use_shifted_data = config["experiment_parameters"]["use_shifted_data"]
    compare_m_model_reward_to_val_sequences = config["experiment_parameters"]["compare_m_model_reward_to_val_sequences"]

    num_workers = config["trainer_parameters"]["num_workers"]
    gpu_id = config["trainer_parameters"]["gpu"]

    manual_seed = config["experiment_parameters"]["manual_seed"]

    set_seeds(manual_seed)
    device = get_device(gpu_id)

    base_save_dir = config["logging_parameters"]["base_save_dir"]
    model_name = config["model_parameters"]["name"]
    debug = config["logging_parameters"]["debug"]
    save_model_checkpoints = config["logging_parameters"]["save_model_checkpoints"]
    scalar_log_frequency = config["logging_parameters"]["scalar_log_frequency"]

    reward_output_activation_function = config["model_parameters"]["reward_output_activation_function"]

    vae_directory = config["vae_parameters"]["directory"]
    vae, vae_name = load_vae_architecture(vae_directory, device, load_best=True)

    vae_config = load_yaml_config(os.path.join(vae_directory, "config.yaml"))
    latent_size = vae_config["model_parameters"]["latent_size"]
    output_activation_function = vae_config["model_parameters"]["output_activation_function"]
    img_size = vae_config["experiment_parameters"]["img_size"]
    vae_dataset_name = vae_config["experiment_parameters"]["dataset"]

    model_type = select_rnn_model(model_name)
    model = model_type(config["model_parameters"], latent_size, batch_size, device).to(device)

    reduce_action_coordinate_space_by: int = config["model_parameters"]["reduce_action_coordinate_space_by"]
    action_transformation_function_type = config["model_parameters"]["action_transformation_function"]

    # optimizer = torch.optim.RMSprop(mdn_rnn.parameters(), lr=learning_rate, alpha=.9)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    # scheduler = ReduceLROnPlateau(optimizer, 'min', factor=0.5, patience=5)
    # earlystopping = EarlyStopping('min', patience=30)

    # if exists(rnn_file) and not args.noreload:
    #     rnn_state = torch.load(rnn_file)
    #     print("Loading MDRNN at epoch {} "
    #           "with test error {}".format(
    #         rnn_state["epoch"], rnn_state["precision"]))
    #     mdrnn.load_state_dict(rnn_state["state_dict"])
    #     optimizer.load_state_dict(rnn_state["optimizer"])
    #     scheduler.load_state_dict(state['scheduler'])
    #     earlystopping.load_state_dict(state['earlystopping'])

    vae_preprocessed_data_path = get_vae_preprocessed_data_path_name(vae_directory, dataset_name)

    if not os.path.exists(vae_preprocessed_data_path):
        preprocess_observations_with_vae(
            rnn_dataset_path=dataset_path,
            vae=vae,
            img_size=img_size,
            output_activation_function=output_activation_function,
            vae_dataset_name=vae_dataset_name,
            device=device,
            vae_preprocessed_data_path=vae_preprocessed_data_path
        )

    additional_dataloader_kwargs = {"num_workers": num_workers, "pin_memory": True}

    reward_transformation_function = get_rnn_reward_transformation_function(
        reward_output_mode=model.get_reward_output_mode(),
        reward_output_activation_function=reward_output_activation_function
    )

    # During training we have data that always uses coordinates in  [0, 447] range therefore use 448 here
    actions_transformation_function = get_rnn_action_transformation_function(
        max_coordinate_size_for_task=448,
        reduce_action_coordinate_space_by=reduce_action_coordinate_space_by,
        action_transformation_function_type=action_transformation_function_type
    )

    _, main_train_data_loader = get_main_rnn_data_loader(
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        split="train",
        sequence_length=sequence_length,
        batch_size=None,  # None to avoid batching, as we only want one sequence dataloader at a time anyway
        actions_transformation_function=actions_transformation_function,
        reward_transformation_function=reward_transformation_function,
        vae_preprocessed_data_path=vae_preprocessed_data_path,
        use_shifted_data=use_shifted_data,
        shuffle=True,
        **additional_dataloader_kwargs
    )

    main_val_dataset, main_val_data_loader = get_main_rnn_data_loader(
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        split="val",
        sequence_length=sequence_length,
        batch_size=None,
        actions_transformation_function=actions_transformation_function,
        reward_transformation_function=reward_transformation_function,
        vae_preprocessed_data_path=vae_preprocessed_data_path,
        use_shifted_data=use_shifted_data,
        shuffle=False,
        **additional_dataloader_kwargs
    )

    if compare_m_model_reward_to_val_sequences:
        # Little bit hacky, but the dataset has to support this option (it has to return the validation sequences).
        # This is not implemented for every dataset so if you want to use the option the correct dataset has to be used.
        # Therefore simply try it early and not after the whole training.
        try:
            main_val_dataset.get_validation_sequences_for_m_model_comparison()
        except NotImplementedError:
            raise RuntimeError(f"The chosen dataset {dataset_name} does not support evaluating the trained M model "
                               "against validation sequences to compare the reward. Try another dataset, for example "
                               "the 'GUIEnvSequencesDatasetRandomWidget500k'.")

        assert save_model_checkpoints, "Evaluating reward against sequences requires storing model weights"

    train_data_loaders = get_individual_rnn_data_loaders(
        rnn_sequence_dataloader=main_train_data_loader,
        batch_size=batch_size,
        shuffle=False,
        **additional_dataloader_kwargs
    )

    val_data_loaders = get_individual_rnn_data_loaders(
        rnn_sequence_dataloader=main_val_data_loader,
        batch_size=batch_size,
        shuffle=False,
        **additional_dataloader_kwargs
    )

    global_train_log_steps = 0
    global_val_log_steps = 0

    if not debug:
        save_dir = os.path.join(base_save_dir, dataset_name)
        summary_writer = ImprovedSummaryWriter(
            log_dir=save_dir,
            comet_config={
                "project_name": "world-models/rnn",
                "disabled": disable_comet
            }
        )

        summary_writer.add_text(tag="Hyperparameter", text_string=pretty_json(config), global_step=0)

        if not disable_comet:
            # noinspection PyProtectedMember
            summary_writer._get_comet_logger()._experiment.set_name(f"version_{summary_writer.version_number}")

        log_dir = summary_writer.get_logdir()
        best_model_filename = os.path.join(log_dir, "best.pt")
        checkpoint_filename = os.path.join(log_dir, "checkpoint.pt")

        save_yaml_config(os.path.join(log_dir, "config.yaml"), config)

        logging.info(f"Started MDN-RNN training version_{summary_writer.version_number} for {max_epochs} epochs")
    else:
        summary_writer = None
        # Enables debugging of the gradient calculation, shows where errors/NaN etc. occur
        torch.autograd.set_detect_anomaly(True)

    current_best = None
    val_loss = None
    for current_epoch in range(max_epochs):
        _, global_train_log_steps = data_pass(model, vae, summary_writer, optimizer,
                                              train_data_loaders, device, tbptt_frequency,
                                              current_epoch, global_train_log_steps, scalar_log_frequency,
                                              train=True, debug=debug)

        val_loss, global_val_log_steps = data_pass(model, vae, summary_writer, optimizer,
                                                   val_data_loaders, device, tbptt_frequency,
                                                   current_epoch, global_val_log_steps, scalar_log_frequency,
                                                   train=False, debug=debug)

        # scheduler.step(test_loss)
        # earlystopping.step(test_loss)
        if not debug:
            is_best = not current_best or val_loss < current_best

            if is_best:
                current_best = val_loss

            if save_model_checkpoints:
                save_checkpoint({
                    "epoch": current_epoch,
                    "state_dict": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    # 'scheduler': scheduler.state_dict(),
                    # 'earlystopping': earlystopping.state_dict(),
                    # "precision": test_loss,
                }, is_best=is_best, checkpoint_filename=checkpoint_filename, best_filename=best_model_filename)

        # if earlystopping.stop:
        #     print("End of Training because of early stopping at epoch {}".format(e))
        #     break

    if not debug and compare_m_model_reward_to_val_sequences:
        logging.info("Starting comparison of rewards between validation sequences and newly trained M model")
        validation_sequences = main_val_dataset.get_validation_sequences_for_m_model_comparison()

        dict_of_sequence_actions = {}
        dict_of_sequence_rewards = {}
        for sequence_length, sequence_list in validation_sequences.items():
            dict_of_sequence_actions[sequence_length] = [seq.actions for seq in sequence_list]

            if model_name == "lstm_bce":
                # Compare also to 0 _or_ 1 rewards because the LSTMBCE model predicts only 0 or 1
                dict_of_sequence_rewards[sequence_length] = [
                    reward_transformation_function(seq.rewards).sum() for seq in sequence_list
                ]
            else:
                dict_of_sequence_rewards[sequence_length] = [seq.rewards.sum() for seq in sequence_list]

        initial_obs_path = generate_initial_observation_latent_vector(vae_directory, device, load_best=True)

        compared_rewards = compare_reward_of_m_model_to_sequence(
            dict_of_sequence_actions=dict_of_sequence_actions,
            rnn_dir=log_dir,
            vae_dir=vae_directory,
            max_coordinate_size_for_task=448,
            device=device,
            initial_obs_path=initial_obs_path,
            load_best_rnn=True,
            render=False
        )

        comparison_loss_function = torch.nn.L1Loss()
        all_rewards = []

        all_comparison_losses = []

        extended_log_info_as_txt = ""
        for i, (sequence_length, achieved_sequence_rewards) in enumerate(compared_rewards.items()):
            all_rewards.extend(achieved_sequence_rewards)

            actual_rewards = dict_of_sequence_rewards[sequence_length]

            comparison_loss = comparison_loss_function(
                torch.tensor(achieved_sequence_rewards), torch.tensor(actual_rewards)
            )
            all_comparison_losses.append(comparison_loss)

            extended_log_info_as_txt += (f"seq_len {sequence_length} # {len(achieved_sequence_rewards)} "
                                         f"- Actual Rew {np.mean(actual_rewards):.6f} "
                                         f"- Cmp {comparison_loss:.6f} "
                                         f"- Max {np.max(achieved_sequence_rewards):.6f} "
                                         f"- Mean {np.mean(achieved_sequence_rewards):.6f} "
                                         f"- Std {np.std(achieved_sequence_rewards):.6f} "
                                         f"- Min {np.min(achieved_sequence_rewards):.6f}  \n")

            summary_writer.add_scalar(f"eval_cmp_rew_{sequence_length}", comparison_loss, global_step=0)

        summary_writer.add_scalar("eval_m_model_rew_min", np.min(all_rewards), global_step=0)
        summary_writer.add_scalar("eval_m_model_rew_max", np.max(all_rewards), global_step=0)
        summary_writer.add_scalar("eval_m_model_rew_mean", np.mean(all_rewards), global_step=0)
        summary_writer.add_scalar("eval_m_model_rew_std", np.std(all_rewards), global_step=0)
        summary_writer.add_scalar(f"eval_cmp_rew_all_mean", np.mean(all_comparison_losses), global_step=0)
        summary_writer.add_scalar(f"eval_cmp_rew_all_std", np.std(all_comparison_losses), global_step=0)
        summary_writer.add_text("eval_cmp_rew_txt", extended_log_info_as_txt, global_step=0)

    if not debug:
        # Use prefix m for model_parameters to avoid possible reassignment of a hparam when combining with
        # experiment_parameters
        model_params = {f"m_{k}": v for k, v in config["model_parameters"].items()}

        for k, v in model_params.items():
            if isinstance(v, list):
                model_params[k] = ", ".join(str(x) for x in v)

        exp_params = {f"e_{k}": v for k, v in config["experiment_parameters"].items()}
        vae_params = {f"v_{k}": v for k, v in config["vae_parameters"].items()}

        hparams = {**model_params, **exp_params, **vae_params}

        summary_writer.add_hparams(
            hparams,
            {"hparams/val_loss": val_loss, "hparams/best_val_loss": current_best},
            name="hparams"  # Since we use one folder per vae training run we can use a fix name here
        )

        # Ensure everything is logged to the tensorboard
        summary_writer.flush()


if __name__ == "__main__":
    main()
