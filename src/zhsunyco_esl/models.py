from dataclasses import dataclass
from enum import Enum

class ColorMode(Enum):
    BW = "BW"
    BWR = "BWR"

@dataclass
class LabelConfig:
    width: int = 296
    height: int = 128
    
    # Standard UUIDs based on the reversed script
    write_char_uuid: str = "00001525-1212-efde-1523-785feabcd123"
    notify_char_uuid: str = "00001526-1212-efde-1523-785feabcd123"

# Default configuration
DEFAULT_CONFIG = LabelConfig()
