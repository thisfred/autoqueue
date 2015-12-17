import os

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False


def player_get_data_dir():
    """Get the directory to store user data.

    Defaults to $XDG_DATA_HOME/autoqueue on Gnome.

    """
    if not XDG:
        data_dir = os.path.join(os.path.expanduser('~'), '.autoqueue')
    else:
        data_dir = os.path.join(
            xdg.BaseDirectory.xdg_data_home, 'autoqueue')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return data_dir
