#!/usr/bin/env python
"""
Hard link completed torrents to completed downloads directory for post
processing. Remove completed torrents based on color label and seed time.
Remove orphaned torrent data.
"""

import argparse
import datetime
import logging
import os
import shutil
import sys
import yaml

import finder_colors
import requests
import transmission

import hardlink

# TODO: Move torrents not matching any known torrents directory to an "other"
#       directory.

logging.basicConfig(format='%(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.expandvars(
    '$HOME/.config/transmission-process-torrents/config.yaml')
DAY_SECONDS = datetime.timedelta(days=1).total_seconds()


class Command(object):

    def __init__(self, config_path=CONFIG_PATH, dry_run=False):
        self.config_path = config_path
        self.dry_run = dry_run

    def __call__(self):
        """
        Process or remove active and orphaned torrent data based on color
        label, ratio, and seed time.
        """

        link = hardlink.Command(dry_run=self.dry_run, force=True)

        # Load config.
        try:
            with open(self.config_path) as file:
                config = yaml.load(file.read())
        except Exception:
            self._err('Unable to load config: %s' % config_path)

        # Get Transmission client.
        host = config.get('transmission_host', 'localhost')
        port = config.get('transmission_port', 9091)
        client = transmission.Transmission(host=host, port=port)

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
            self._err('Unable to connect to Transmission at %s:%s' % (
                host,
                port,
            ))

        # Store torrents found in a known torrents directory for later
        # processing.
        found_torrents = set()

        # Hard link or remove completed torrents.
        for torrent in torrents:
            absolute_path = os.path.join(
                torrent['downloadDir'], torrent['name'])

            # Map remote paths.
            for remote_path, local_path in \
                    config['mapped_remote_paths'].items():
                if absolute_path.startswith(remote_path):
                    absolute_path = absolute_path.replace(
                        remote_path, local_path)

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
                        downloaded and
                        finder_colors.get(absolute_path) != 'none')

                    # Get seeding status.
                    seeding = bool(
                        ratio and
                        ratio > torrent['uploadRatio'] or
                        seed_days and
                        seed_days * DAY_SECONDS > torrent['secondsSeeding'])

                    # Hard link downloaded torrents to the post processing
                    # directory.
                    if downloaded and not processed:
                        logger.info('Processing torrent: %s' % absolute_path)
                        destination = os.path.join(
                            post_processing_dir,
                            os.path.relpath(absolute_path, download_dir),
                        )
                        link(absolute_path, destination)
                        if not self.dry_run:
                            finder_colors.set(absolute_path, 'green')

                    # Remove processed torrents that have finished seeding.
                    elif processed and not seeding:
                        logger.info(
                            'Removing inactive torrent: %s' % torrent['name'])
                        if not self.dry_run:
                            client(
                                'torrent-remove',
                                ids=[torrent['id']],
                                delete_local_data=True,
                            )

                    else:
                        # Ignore torrents that are still downloading or seeding.
                        logger.debug('Skipping active torrent: %s' % absolute_path)

                    # Log torrent data, regardless of action taken.
                    logger.debug(' - Downloaded: %d%%' % (
                        torrent['percentDone'] * 100))
                    if ratio:
                        logger.debug(' - Ratio: %.2f (%s)' % (
                            torrent['uploadRatio'],
                            ratio,
                        ))
                    if seed_days:
                        logger.debug(' - Seed Time: %.2f (%s) days' % (
                            torrent['secondsSeeding'] / DAY_SECONDS,
                            seed_days,
                        ))

                    # We found a match. No need to continue.
                    break

            # No matching torrents directory.
            else:
                logger.debug(
                    'Skipping torrent not located in any download directory: '
                    '%s' % absolute_path)

        # Process orphaned torrent data in download directories.
        for dir_config in config['torrent_dirs']:
            download_dir = dir_config['download_dir']
            post_processing_dir = dir_config['post_processing_dir']

            # Compare every file and directory in the download directory to
            # previously found torrents. Remove anything already processed and
            # not belonging to a found torrent. Hard link everything else to
            # the post processing directory.
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
                    processed = bool(
                        finder_colors.get(absolute_path) != 'none')

                    # Hard link orphaned files that have not been processed.
                    if not processed:
                        logger.info(
                            'Processing orphaned file or directory: %s' %
                            absolute_path)
                        destination = os.path.join(
                            post_processing_dir,
                            os.path.relpath(absolute_path, download_dir),
                        )
                        link(absolute_path, destination)
                        if not self.dry_run:
                            finder_colors.set(absolute_path, 'green')

                    # Remove orphaned files that have been processed.
                    logger.info(
                        'Removing orphaned file or directory: %s' %
                        absolute_path)
                    if not self.dry_run:
                        try:
                            shutil.rmtree(absolute_path)
                        except OSError:
                            os.remove(absolute_path)

    def _err(self, *args):
        """
        Log error and exit.
        """
        logger.error(*args)
        exit(1)


def main():
    # Parse arguments.
    parser = argparse.ArgumentParser(
        description='Hard links downloaded torrents to a post processing '
                    'directory and removes them once ratio and seed time '
                    'requirements have been satisfied.',
    )
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        '-c',
        '--config',
        default=CONFIG_PATH,
        help='Path to config file. (Default: %(default)s)',
        metavar='PATH',
    )
    parser.add_argument(
        '-d',
        '--dry-run',
        action='store_true',
        help='Do not link or remove torrents. Only log operations.',
    )
    group.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='Silence standard output.',
    )
    parser.add_argument(
        '-s',
        '--sample-config',
        action='store_true',
        help='Dump sample config to standard output.',
    )
    group.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        dest='verbosity',
        help='Increase verbosity for each occurrence.',
    )
    args = parser.parse_args()

    # Configure log level with verbosity argument.
    levels = (
        # logging.CRITICAL,
        # logging.ERROR,
        logging.WARNING,
        logging.INFO,
        logging.DEBUG,
    )
    try:
        logger.setLevel(levels[args.verbosity])
    except IndexError:
        logger.setLevel(logging.DEBUG)

    # Dump sample config file to standard output.
    if args.sample_config:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'config-sample.yaml')
        with open(config_path) as file:
            sys.stdout.write(file.read())

    else:
        # Silence standard output.
        stdout = sys.stdout
        if args.quiet:
            sys.stdout = open(os.devnull, 'w')
        # Execute.
        Command(args.config, args.dry_run)()
        # Restore standard output.
        sys.stdout = stdout

if __name__ == '__main__':
    main()
