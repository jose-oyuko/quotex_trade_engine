"""Everything Deriv-related (decisions D-74 to D-77). Only this package talks to Deriv."""

from app.deriv.adapter import DerivAdapter
from app.deriv.fake import FakeDerivAdapter

__all__ = ["DerivAdapter", "FakeDerivAdapter"]
