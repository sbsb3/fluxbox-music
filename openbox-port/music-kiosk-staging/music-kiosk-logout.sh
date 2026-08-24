#!/bin/sh
# /usr/local/bin/music-kiosk-logout
# Graphical confirmation dialog (zenity), then loginctl terminate-user to
# end the Music Kiosk session.  loginctl terminate-user "$USER" kills all
# of the user's sessions (the kiosk X session included); LightDM then
# returns to the greeter.
#
# If polkit demands interactive auth for this action and no polkit agent
# is running in the kiosk, loginctl will fail silently -- start
# polkit-gnome in music-kiosk.sh or add a sudoers rule if so.

if zenity --question \
    --title="Log out of Music Kiosk?" \
    --text="End the session? Any unsaved work in open DAWs will be lost." \
    --ok-label="Log out" \
    --cancel-label="Cancel" 2>/dev/null; then
    loginctl terminate-user "$USER"
fi
