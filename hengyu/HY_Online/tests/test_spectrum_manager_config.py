from __future__ import annotations

import pytest

from spectrum_manager import SpectrumAcquisitionManager


def test_ema_smoothing_reduces_single_point_spike():
    manager = SpectrumAcquisitionManager()
    manager.set_smoothing_config(enabled=True, alpha=0.5)

    smoothed, did_smooth, alpha = manager._apply_ema_smoothing([0.0, 10.0, 0.0])

    assert did_smooth is True
    assert alpha == 0.5
    assert len(smoothed) == 3
    assert max(smoothed) < 10.0


def test_ema_smoothing_can_be_disabled():
    manager = SpectrumAcquisitionManager()
    source = [0.0, 10.0, 0.0]
    manager.set_smoothing_config(enabled=False)

    smoothed, did_smooth, alpha = manager._apply_ema_smoothing(source)

    assert smoothed is source
    assert did_smooth is False
    assert alpha is None


def test_ema_smoothing_rejects_invalid_alpha():
    manager = SpectrumAcquisitionManager()

    with pytest.raises(ValueError):
        manager.set_smoothing_config(alpha=0.0)
