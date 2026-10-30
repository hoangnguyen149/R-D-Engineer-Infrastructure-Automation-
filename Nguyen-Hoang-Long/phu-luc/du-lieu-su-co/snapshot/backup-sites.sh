#!/bin/bash
# /usr/local/bin/backup-sites.sh  (cron 01:00 hằng ngày)
set -o pipefail
DEST=/var/backups
TODAY=$(date +%Y%m%d)
OLD=$(date -d '1 day ago' +%Y%m%d)
logger -t backup-sites "start backup /home -> $DEST/sites-$TODAY.tar.gz"
if tar -czf "$DEST/sites-$TODAY.tar.gz" /home 2>&1 | logger -t backup-sites; then
    SIZE=$(du -h "$DEST/sites-$TODAY.tar.gz" | cut -f1)
    logger -t backup-sites "backup done size=$SIZE"
    rm -f "$DEST/sites-$OLD.tar.gz" && logger -t backup-sites "removed old backup sites-$OLD.tar.gz"
else
    logger -t backup-sites "ERROR backup failed exit=$?, keep old backups"
fi
