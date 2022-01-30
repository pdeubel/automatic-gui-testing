from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as f

from models.rnn import BaseSimpleRNN


class LSTM(BaseSimpleRNN):

    def __init__(self, model_parameters: dict, latent_size: int, batch_size: int, device: torch.device):
        super().__init__(model_parameters, latent_size, batch_size, device)

        self.rnn = nn.LSTM(input_size=self.latent_size + self.action_size, hidden_size=self.hidden_size,
                           batch_first=True)
        self.fc = nn.Linear(self.hidden_size, self.latent_size + 1)


class LSTMWithBCE(LSTM):

    def __init(self, **kwargs):
        super().__init__(**kwargs)

    def predict(self, model_output, latents=None):
        # This function mostly exists for mixture density network as the actual calculation of the next latent state
        # is not required for training, just the calculation of the predicted probability distribution.
        # But since we want to use the same interface, just return the prediction here
        return model_output[0], torch.sigmoid(model_output[1])

    def forward(self, latents: torch.Tensor, actions: torch.Tensor):
        outputs, _ = self.rnn_forward(latents, actions)

        predictions = self.fc(outputs)

        predicted_latent_vector = predictions[:, :, :self.latent_size]
        predicted_reward = predictions[:, :, self.latent_size:]

        return predicted_latent_vector, predicted_reward

    def loss_function(self, next_latent_vector: torch.Tensor, reward: torch.Tensor, model_output: Tuple):
        predicted_latent, predicted_reward = model_output[0], model_output[1]

        # TODO check if reduction needs to be adapted to batch size and sequence length
        latent_loss = f.mse_loss(predicted_latent, next_latent_vector)

        # Computes sigmoid followed by BCELoss. Is numerically more stable than doing the two steps separately, see
        # https://pytorch.org/docs/stable/generated/torch.nn.BCEWithLogitsLoss.html
        reward_loss = f.binary_cross_entropy_with_logits(predicted_reward, reward.greater(0).float().unsqueeze(-1))
        loss = self.combine_latent_and_reward_loss(latent_loss=latent_loss, reward_loss=reward_loss)

        return loss, (latent_loss.item(), reward_loss.item())


class LSTMWithMSE(LSTM):

    def __init(self, **kwargs):
        super().__init__(**kwargs)