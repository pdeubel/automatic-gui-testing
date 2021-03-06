from typing import Tuple

import torch
from torch import nn

from models.vae import BaseVAE


class LargeVAESmallKernels(BaseVAE):

    def __init__(self, model_parameters: dict, use_kld_warmup: bool, kld_weight: float = 1.0):
        super().__init__(model_parameters, use_kld_warmup, kld_weight)

        self.conv_1 = nn.Sequential(
            nn.Conv2d(in_channels=self.input_channels, out_channels=16, kernel_size=7, stride=1, padding=3),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_2 = nn.Sequential(
            nn.Conv2d(in_channels=16, out_channels=32, kernel_size=5, stride=1, padding=2),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_3 = nn.Sequential(
            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_4 = nn.Sequential(
            nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_5 = nn.Sequential(
            nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_6 = nn.Sequential(
            nn.Conv2d(in_channels=256, out_channels=512, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.fc_mu = nn.Linear(7*7*512, self.latent_size)
        self.fc_log_var = nn.Linear(7*7*512, self.latent_size)

        self.fc_decoder = nn.Linear(self.latent_size, 7*7*512)

        self.transposed_conv_1 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=512, out_channels=256, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_2 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=256, out_channels=128, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_3 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=128, out_channels=64, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_4 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=64, out_channels=32, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_5 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=32, out_channels=16, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_6 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=16, out_channels=self.input_channels,
                               kernel_size=7, stride=2, padding=3, output_padding=1),
            nn.Sigmoid()
        )

    def encode(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        x = self.conv_1(x)
        x = self.conv_2(x)
        x = self.conv_3(x)
        x = self.conv_4(x)
        x = self.conv_5(x)
        x = self.conv_6(x)
        x = x.view(x.size(0), -1)

        mu = self.fc_mu(x)
        log_var = self.fc_log_var(x)

        return mu, log_var

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        x = self.fc_decoder(z)
        x = x.view(x.size(0), 512, 7, 7)

        x = self.transposed_conv_1(x)
        x = self.transposed_conv_2(x)
        x = self.transposed_conv_3(x)
        x = self.transposed_conv_4(x)
        x = self.transposed_conv_5(x)
        x = self.transposed_conv_6(x)

        return x


class EvenLargerVAESmallKernels(BaseVAE):

    def __init__(self, model_parameters: dict, use_kld_warmup: bool, kld_weight: float = 1.0):
        super().__init__(model_parameters, use_kld_warmup, kld_weight)

        self.conv_1 = nn.Sequential(
            nn.Conv2d(in_channels=self.input_channels, out_channels=16, kernel_size=7, stride=1, padding=3),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_2 = nn.Sequential(
            nn.Conv2d(in_channels=16, out_channels=32, kernel_size=5, stride=1, padding=2),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_3 = nn.Sequential(
            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_4 = nn.Sequential(
            nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_5 = nn.Sequential(
            nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_6 = nn.Sequential(
            nn.Conv2d(in_channels=256, out_channels=512, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.conv_7 = nn.Sequential(
            nn.Conv2d(in_channels=512, out_channels=512, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2, padding=1),
            nn.LeakyReLU()
        )

        self.conv_8 = nn.Sequential(
            nn.Conv2d(in_channels=512, out_channels=512, kernel_size=3, stride=1, padding=1),
            nn.MaxPool2d(kernel_size=2, stride=2),
            nn.LeakyReLU()
        )

        self.fc_mu = nn.Linear(2*2*512, self.latent_size)
        self.fc_log_var = nn.Linear(2*2*512, self.latent_size)

        self.fc_decoder = nn.Linear(self.latent_size, 2*2*512)

        self.transposed_conv_00 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=512, out_channels=512, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_01 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=512, out_channels=512, kernel_size=3, stride=2, padding=1, output_padding=0),
            nn.LeakyReLU()
        )

        self.transposed_conv_1 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=512, out_channels=256, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_2 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=256, out_channels=128, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_3 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=128, out_channels=64, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_4 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=64, out_channels=32, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_5 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=32, out_channels=16, kernel_size=3, stride=2, padding=1, output_padding=1),
            nn.LeakyReLU()
        )

        self.transposed_conv_6 = nn.Sequential(
            nn.ConvTranspose2d(in_channels=16, out_channels=self.input_channels,
                               kernel_size=7, stride=2, padding=3, output_padding=1),
            nn.Sigmoid()
        )

    def encode(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        x = self.conv_1(x)
        x = self.conv_2(x)
        x = self.conv_3(x)
        x = self.conv_4(x)
        x = self.conv_5(x)
        x = self.conv_6(x)
        x = self.conv_7(x)
        x = self.conv_8(x)
        x = x.view(x.size(0), -1)

        mu = self.fc_mu(x)
        log_var = self.fc_log_var(x)

        return mu, log_var

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        x = self.fc_decoder(z)
        x = x.view(x.size(0), 512, 2, 2)

        x = self.transposed_conv_00(x)
        x = self.transposed_conv_01(x)
        x = self.transposed_conv_1(x)
        x = self.transposed_conv_2(x)
        x = self.transposed_conv_3(x)
        x = self.transposed_conv_4(x)
        x = self.transposed_conv_5(x)
        x = self.transposed_conv_6(x)

        return x


def main():
    from torchinfo import summary

    model = EvenLargerVAESmallKernels({
        "input_channels": 3,
        "latent_size": 32
    }, True, 1.0)
    summary(model, input_size=(1, 3, 448, 448))


if __name__ == "__main__":
    main()
