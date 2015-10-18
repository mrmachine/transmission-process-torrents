#!/usr/bin/env python
"""
Hard link completed torrents to completed downloads directory for post
processing. Remove completed torrents based on color label and seed time.
Remove orphaned torrent data.
"""

import argparse
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

CONFIG_PATH = os.path.expandvars(
    '$HOME/.config/transmission-process-torrents/config.yaml')
DAY_SECONDS = datetime.timedelta(days=1).total_seconds()


def err(stderr):
    sys.stderr.write('%s\n' % stderr.strip())
    exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Hard link downloaded torrents to a post processing '
                    'directory. Remove processed torrents that have already '
                    'satisfied their ratio and seed time requirements.',
    )
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        '-c',
        '--config',
        default=CONFIG_PATH,
        help='path to config file',
        metavar='PATH',
    )
    parser.add_argument(
        '-d',
        '--dry-run',
        action='store_true',
        help='simulate results',
    )
    group.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='silence standard output',
    )
    parser.add_argument(
        '-s',
        '--sample-config',
        action='store_true',
        help='dump sample config to standard output',
    )
    group.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        dest='verbosity',
        help='increase verbosity of standard output for each occurrence, e.g. '
             '-vv',
    )
    args = parser.parse_args()

    # Dump sample config file to standard output.
    if args.sample_config:
        config_path = os.path.join(
            os.path.dirname(__file__), 'config-sample.yaml')
        with open(config_path) as file:
            sys.stdout.write(file.read())

    # Execute normally.
    else:
        # Silence standard output. No need to use a context manager or restore
        # the original stdout because `main()` will exit immediately after.
        if args.quiet:
            sys.stdout = open(os.devnull, 'w')
        process_torrents(
            config_path=args.config,
            dry_run=args.dry_run,
            verbosity=args.verbosity,
        )
        exit()


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


def process_torrents(config_path=CONFIG_PATH, dry_run=False, verbosity=0):
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
                elif verbosity:
                    sys.stdout.write(
                        'Skipping active torrent: %s\n' % absolute_path)

                # Log torrent data, regardless of action taken.
                print_data(torrent, ratio, seed_days, verbosity)

                # We found a match. No need to continue.
                break

        # No matching torrents directory.
        else:
            if verbosity:
                sys.stdout.write(
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
                sys.stdout.write(
                    'Removing orphaned file or directory: %s\n' %
                    absolute_path)
                if not dry_run:
                    try:
                        shutil.rmtree(absolute_path)
                    except OSError:
                        os.remove(absolute_path)

if __name__ == '__main__':
    main()
