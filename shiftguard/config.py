"""Central configuration for ShiftGuard-SHM."""
from dataclasses import dataclass, field


@dataclass
class Config:
    # ---- sensing / windows ----
    n_sensors: int = 8            # number of accelerometer channels used
    fs: float = 100.0             # sampling rate (Hz) – Z24 and the virtual bridge both use 100 Hz
    win: int = 2048               # samples per monitoring window (~20 s)

    # ---- features (log band-power spectrum per sensor) ----
    band_lo: float = 1.0
    band_hi: float = 30.0
    n_bands: int = 16
    nperseg: int = 256

    # ---- healthy-behaviour model ----
    model: str = "mlp"            # "mlp" = masked-sensor network, "ridge" = fast linear variant
    use_temperature: bool = True  # temperature (FiLM-style) conditioning; False = ablation
    use_masking: bool = True      # mask-and-impute the most suspicious sensor; False = ablation
    mlp_hidden: tuple = (256, 128)
    mlp_max_iter: int = 200

    # ---- sequential alarm layer (conformal e-detectors) ----
    alarm_level: float = 1e4      # E[windows until a false alarm] >= alarm_level  (1e4 h ~ 14 months)
    cap_factor: float = 10.0      # evidence is capped at cap_factor*alarm_level so detectors recover
    eps_grid: tuple = (0.05, 0.1, 0.2, 0.3, 0.5)   # power-calibrator mixture (p -> e)
    env_k: int = 25               # k-nearest-neighbour size for the environment-novelty score
    use_env_monitor: bool = True
    local_k: int = 400            # temperature-localised conformal calibration (0 = global ranks)

    # ---- severity stage ----
    severity_alpha: float = 0.1   # conformal prediction sets with >= 90 % coverage

    seed: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def cap(self):
        return self.alarm_level * self.cap_factor
