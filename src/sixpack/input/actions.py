from enum import Enum, auto


class InputAction(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    SELECT = auto()
    BACK = auto()

    PLAY_PAUSE = auto()
    STOP = auto()
    SEEK_FORWARD = auto()
    SEEK_BACK = auto()
    SEEK_FORWARD_LONG = auto()
    SEEK_BACK_LONG = auto()
    NEXT_CHAPTER = auto()
    PREV_CHAPTER = auto()
    NEXT_ITEM = auto()
    PREV_ITEM = auto()

    MENU = auto()
