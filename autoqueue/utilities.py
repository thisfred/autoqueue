import os


def player_get_data_dir():
    """Get the directory to store user data.

    Defaults to $XDG_DATA_HOME/autoqueue on Gnome.

    """
    data_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "autoqueue")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return data_dir
