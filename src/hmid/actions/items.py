"""Panel menu items (MSI Center's Enum_TouchModeIndex).

The panel runs its own touch menu and reports the selected function as an item number
in every status packet; a change of that number is a tap.
"""

ITEM_NAMES = {
    1: "Shortcut_MsiCenter", 2: "Shortcut_user1", 3: "Shortcut_user2", 4: "Shortcut_user3",
    5: "Shortcut_user4", 6: "Shortcut_user5",
    10: "Nahimic_Music", 11: "Nahimic_Gaming", 12: "Nahimic_Movie", 13: "Nahimic_Communication", 14: "Nahimic_SMART",
    20: "Volume_Speaker_Up", 21: "Volume_Speaker_Down", 22: "Volume_Speaker_Mute",
    23: "Volume_Speaker_25", 24: "Volume_Speaker_50", 25: "Volume_Speaker_75", 26: "Volume_Speaker_100",
    27: "Volume_Mic_Up", 28: "Volume_Mic_Down", 29: "Volume_Mic_Mute",
    30: "Volume_Mic_25", 31: "Volume_Mic_50", 32: "Volume_Mic_75", 33: "Volume_Mic_100",
    40: "UserScenario_Extreme", 41: "UserScenario_Balanced", 42: "UserScenario_Silent",
    43: "UserScenario_None", 44: "UserScenario_Creator", 45: "UserScenario_Customize",
    50: "Music_VolumeUp", 51: "Music_VolumeDown", 52: "Music_Mute",
    53: "Music_NextTrack", 54: "Music_PreviousTrack", 55: "Music_PlayPause",
    60: "FreeUpMemory", 70: "CountdownTimer_Alarm", 71: "CountdownTimer_Stop",
    80: "MysticLight_Off", 81: "MysticLight_Default", 82: "MysticLight_Steady", 83: "MysticLight_Breathing",
    84: "MysticLight_Flashing", 85: "MysticLight_DoubleFlashing", 86: "MysticLight_Visor", 87: "MysticLight_Stack",
    88: "MysticLight_Marquee", 89: "MysticLight_CPUTemp", 90: "MysticLight_Meteor", 91: "MysticLight_Lighting",
    92: "MysticLight_Rainbow", 93: "MysticLight_ColorRing", 94: "MysticLight_ColorShift", 95: "MysticLight_Random",
    96: "MysticLight_POP", 97: "MysticLight_RAP", 98: "MysticLight_JAZZ", 99: "MysticLight_Play", 100: "MysticLight_Movie",
    110: "GamingMode_On", 111: "GamingMode_Off",
    221: "OSDMenu_NotSupport", 230: "GI_Off",
    240: "PowerFunction_S3", 241: "PowerFunction_Reboot", 242: "PowerFunction_S5",
    250: "Shortcut_user6", 251: "Shortcut_user7", 252: "Shortcut_user8",
    253: "Shortcut_user9", 254: "Shortcut_user10", 255: "Shortcut_user11",
}

ALARM = 70
ALARM_STOP = 71
MYSTIC_CPU_TEMP = 89
MYSTIC_RANGE = range(80, 101)


def name(item: int) -> str:
    return ITEM_NAMES.get(item, f"item_{item}")
