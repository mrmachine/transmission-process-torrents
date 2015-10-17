#!/usr/bin/env python
"""
Hard link completed torrents to completed downloads directory for post
processing. Remove completed torrents based on color label and seed time.
Remove orphaned torrent data.
"""

import datetime
import os
import requests
import shutil
import sys
import transmission
import yaml

import finder_colors

from hardlink import hardlink

# TODO: Move torrents not matching any known torrents directory to an "other"
#       directory.

DRY_RUN = False  # Do not hard link or remove files or torrents
VERBOSITY = 1  # 0 = no output, 1 = output action, 2 = output torrent data

DAY_SECONDS = datetime.timedelta(days=1).total_seconds()

CONFIG_PATH = os.path.expandvars(
    '$HOME/.config/transmission-process-torrents/config.yaml')


def print_data(torrent, ratio, seed_days, verbosity):
    if verbosity >= 2:
        sys.stdout.write(
            ' - Downloaded: %d%%\n' % (torrent['percentDone'] * 100))
        if ratio:
            sys.stdout.write(' - Ratio: %.2f (%s)\n' % (
                torrent['uploadRatio'],
                ratio,
            ))
        if seed_days:
            sys.stdout.write(' - Seed Time: %.2f (%s) days\n' % (
                torrent['secondsSeeding'] / DAY_SECONDS,
                seed_days,
            ))


def process_torrents(
        config_path=CONFIG_PATH, dry_run=DRY_RUN, verbosity=VERBOSITY):
    """
    Process or remove active and orphaned torrent data based on color label,
    ratio, and seed time.
    """
    # Load config.
    try:
        with open(config_path) as file:
            config = yaml.load(file.read())
    except Exception:
        err('Error: Unable to load config: %s' % config_path)

    # Get Transmission client.
    client = transmission.Transmission(
        host=config.get('transmission_host', 'localhost'),
        port=config.get('transmission_port', 9091),
    )

    # Get torrents from Transmission.
    try:
        torrents = client('torrent-get', fields=[
            'downloadDir',
            'id',
            'name',
            'percentDone',
            'secondsSeeding',
            'uploadRatio',
        ])['torrents']
    except requests.ConnectionError:
        err('Error: Unable to connect to Transmission')

    # Store torrents found in a known torrents directory for later processing.
    found_torrents = set()

    # Hard link or remove completed torrents.
    for torrent in torrents:
        absolute_path = os.path.join(torrent['downloadDir'], torrent['name'])

        # Map remote paths.
        for remote_path, local_path in config['mapped_remote_paths'].items():
            if absolute_path.startswith(remote_path):
                absolute_path = absolute_path.replace(remote_path, local_path)

        # Find matching torrents directory.
        for dir_config in config['torrent_dirs']:

            # Get config for torrent directory.
            download_dir = dir_config['download_dir']
            post_processing_dir = dir_config['post_processing_dir']
            ratio = dir_config.get('ratio')
            seed_days = dir_config.get('seed_days')

            if absolute_path.startswith(download_dir):
                found_torrents.add(absolute_path)

                # Get downloaded and seeding status.
                downloaded = bool(torrent['percentDone'] == 1)

                # Assume already processed if a color label is set.
                processed = bool(
                    downloaded and finder_colors.get(absolute_path) != 'none')

                # Get seeding status.
                seeding = bool(
                    ratio and
                    ratio > torrent['uploadRatio'] or
                    seed_days and
                    seed_days * DAY_SECONDS > torrent['secondsSeeding'])

                # Hard link downloaded torrents to post processing directory.
                if downloaded and not processed:
                    if verbosity:
                        sys.stdout.write(
                            'Processing torrent: %s\n' %
                            absolute_path)
                    destination = os.path.join(
                        post_processing_dir,
                        os.path.relpath(absolute_path, download_dir),
                    )
                    if not dry_run:
                        hardlink(absolute_path, destination, force=True)
                        finder_colors.set(absolute_path, 'green')

                # Remove processed torrents that have finished seeding.
                elif processed and not seeding:
                    if verbosity:
                        sys.stdout.write(
                            'Removing inactive torrent: %s\n' %
                            torrent['name'])
                    if not dry_run:
                        client(
                            'torrent-remove',
                            ids=[torrent['id']],
                            delete_local_data=True,
                        )

                # Ignore torrents that are still downloading or seeding.
                else:
                    if verbosity:
                        sys.stdout.write(
                            'Skipping active torrent: %s\n' % absolute_path)

                # Log torrent data, regardless of action taken.
                print_data(torrent, ratio, seed_days, verbosity)

                # We found a match. No need to continue.
                break

        # No matching torrents directory.
        else:
            if verbosity:
                sys.stderr.write(
                    'Skipping torrent not located in any download directory: '
                    '%s\n' % absolute_path)

    # Process orphaned torrent data in download directories.
    for dir_config in config['torrent_dirs']:
        download_dir = dir_config['download_dir']
        post_processing_dir = dir_config['post_processing_dir']

        # Compare every file and directory in the download directory to
        # previously found torrents. Remove anything already processed and not
        # belonging to a found torrent. Hard link everything else to the post
        # processing directory.
        for path in os.listdir(download_dir):

            # Ignore hidden files, e.g. dot-underscore files on OS X.
            if path.startswith('.'):
                continue

            absolute_path = os.path.join(download_dir, path)

            # Find matching torrent for this path.
            for found_torrent in found_torrents:
                if absolute_path.startswith(found_torrent):
                    # We found a match. No need to continue.
                    break

            # No matching torrent.
            else:

                # Assume already processed if a color label is set.
                processed = bool(finder_colors.get(absolute_path) != 'none')

                # Hard link orphaned files that have not been processed.
                if not processed:
                    if verbosity:
                        sys.stdout.write(
                            'Processing orphaned file or directory: %s\n' %
                            absolute_path)
                    destination = os.path.join(
                        post_processing_dir,
                        os.path.relpath(absolute_path, download_dir),
                    )
                    if not dry_run:
                        hardlink(absolute_path, destination, force=True)
                        finder_colors.set(absolute_path, 'green')

                # Remove orphaned files that have been processed.
                if verbosity:
                    sys.stdout.write(
                        'Removing orphaned file or directory: %s\n' %
                        absolute_path)
                if not dry_run:
                    try:
                        shutil.rmtree(absolute_path)
                    except OSError:
                        os.remove(absolute_path)


def err(stderr):
    sys.stderr.write('%s\n' % stderr.strip())
    exit(1)


def main():
    if len(sys.argv) not in [1, 2]:
        message = 'Usage: %s [config=%s]' % (
            os.path.basename(sys.argv[0]),
            CONFIG_PATH,
        )
        err(message)
    process_torrents(*sys.argv[1:])


if __name__ == '__main__':
    main()
