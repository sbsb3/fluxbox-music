#!/bin/sh
# /usr/local/bin/music-kiosk-logout
# Graphical confirmation dialog (zenity), then loginctl terminate-user to
# end the Music Kiosk session.  loginctl terminate-user "$USER" kills all
# of the user's sessions (the kiosk X session included); LightDM then
# returns to the greeter.
#
# Single-instance guard: Plank doesn't track whether the launched app is
# already running, so each click re-execs this script.  Without the guard,
# if the first dialog is briefly hidden behind a fullscreen DAW the user
# clicks again and piles up duplicates.  flock on a lockfile ensures only
# the first invocation reaches zenity; further clicks while it's up exit
# immediately.  The lock auto-releases when the holder exits (fd closed).
#
# Visibility: rc.xml puts type="dialog" windows in the `above` layer so
# zenity stacks over the fullscreen DAW.  If dialogs still hide, see that
# rule (openbox-music-kiosk/rc.xml) -- not something this script can fix.
#
# If polkit demands interactive auth for this action and no polkit agent
# is running in the kiosk, loginctl will fail silently -- start
# polkit-gnome in music-kiosk.sh or add a sudoers rule if so.

exec 9>/tmp/music-kiosk-logout.lock
if ! flock -n 9; then
    # Another instance is already showing the dialog; don't stack more.
    exit 0
fi

if zenity --question \
    --title="Log out of Music Kiosk?" \
    --text="End the session? Any unsaved work in open DAWs will be lost." \
    --ok-label="Log out" \
    --cancel-label="Cancel" 2>/dev/null; then
    loginctl terminate-user "$USER"
fi
