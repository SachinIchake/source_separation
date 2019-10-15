import torch
import torch.nn as nn
from typing import Tuple, Dict
from pytorch_sound.trainer import Trainer, LogType


class Wave2WaveTrainer(Trainer):

    def __init__(self, model: nn.Module, optimizer,
                 train_dataset, valid_dataset,
                 max_step: int, valid_max_step: int, save_interval: int, log_interval: int,
                 save_dir: str, save_prefix: str = '',
                 grad_clip: float = 0.0, grad_norm: float = 0.0,
                 sr: int = 22050,
                 pretrained_path: str = None, scheduler: torch.optim.lr_scheduler._LRScheduler = None):
        super().__init__(model, optimizer, train_dataset, valid_dataset,
                         max_step, valid_max_step, save_interval, log_interval, save_dir, save_prefix,
                         grad_clip, grad_norm, pretrained_path, sr=sr, scheduler=scheduler)
        # loss
        self.mse_loss = nn.MSELoss()

        # module
        if isinstance(self.model, nn.DataParallel):
            self.module = self.model.module
        else:
            self.module = self.model

    def l1_loss(self, clean_hat, clean):
        return torch.abs(clean_hat - clean).mean()

    def wsrd_loss(self, clean_hat, clean, noise, eps: float = 1e-5):
        # calc norm
        clean_norm = clean.norm(dim=1)
        clean_hat_norm = clean_hat.norm(dim=1)
        minus_c_norm = (noise - clean).norm(dim=1)
        minus_ch_norm = (noise - clean_hat).norm(dim=1)

        # calc alpha
        alpha = clean_norm ** 2 / (clean_norm ** 2 + minus_c_norm ** 2 + eps)

        # calc loss
        loss_left = - alpha * (clean * clean_hat).sum(dim=1) / (clean_norm * clean_hat_norm + eps)
        loss_right = - (1 - alpha) * ((noise - clean) * (noise - clean_hat)).sum(dim=1) / (minus_c_norm * minus_ch_norm + eps)
        loss = (loss_left + loss_right).mean()
        return loss

    def forward(self, noise, clean, *args, is_logging: bool = False) -> Tuple[torch.Tensor, Dict]:
        # forward
        res = self.model(noise)
        if isinstance(res, tuple):
            clean_hat, *_ = res
        else:
            clean_hat = res

        # calc loss
        # loss = self.mse_loss(clean_hat, clean[..., :clean_hat.size(-1)])
        # loss = self.l1_loss(clean_hat, clean[..., :clean_hat.size(-1)])
        loss = self.wsrd_loss(clean_hat, clean, noise)

        if is_logging:
            clean_hat = clean_hat[0]
            clean = clean[0]
            noise = noise[0]

            meta = {
                'wsrd_loss': (loss.item(), LogType.SCALAR),
                'clean_hat.audio': (clean_hat, LogType.AUDIO),
                'clean.audio': (clean, LogType.AUDIO),
                'noise.audio': (noise, LogType.AUDIO),
                'clean_hat.plot': (clean_hat, LogType.PLOT),
                'clean.plot': (clean, LogType.PLOT),
                'noise.plot': (noise, LogType.PLOT),
            }
        else:
            meta = {}

        return loss, meta


class LossMixingTrainer(Wave2WaveTrainer):

    def forward(self, noise, clean, *args, is_logging: bool = False) -> Tuple[torch.Tensor, Dict]:
        # forward
        clean_hat, mag_hat, phase_hat = self.model(noise)

        # calc losses
        # make spectrogram of clean wave
        clean_mag, clean_phase = self.module.log_stft(clean)
        # calc l1 loss on magnitude
        mag_l1_loss = self.l1_loss(mag_hat, clean_mag)
        # calc loss
        wsrd_loss = self.wsrd_loss(clean_hat, clean, noise)

        loss = mag_l1_loss + wsrd_loss

        if is_logging:
            clean_hat = clean_hat[0]
            clean = clean[0]
            noise = noise[0]

            meta = {
                'total_loss': (loss.item(), LogType.SCALAR),
                'wsrd_loss': (wsrd_loss.item(), LogType.SCALAR),
                'mag_l1_loss': (mag_l1_loss.item(), LogType.SCALAR),
                'clean_hat.audio': (clean_hat, LogType.AUDIO),
                'clean.audio': (clean, LogType.AUDIO),
                'noise.audio': (noise, LogType.AUDIO),
                'clean_hat.plot': (clean_hat, LogType.PLOT),
                'clean.plot': (clean, LogType.PLOT),
                'noise.plot': (noise, LogType.PLOT),
            }
        else:
            meta = {}

        return loss, meta
