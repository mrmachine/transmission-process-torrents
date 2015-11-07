#!/usr/bin/env python
"""
Hard link completed torrents to completed downloads directory for post
processing. Remove processed torrents when ratio and seed time requirements are
satisfied. Remove orphaned torrent data.
"""

import argparse
import datetime
import jsondict
import logging
import os
import shutil
import sys
import yaml

import requests
import transmission

import hardlink


# TODO:
# - Move torrents not matching any known torrents directory to an "other"
#   directory.
# - Keep a separate database for each torrents directory, in the torrents
#   directory, and store processed state for torrent names instead of absolute
#   paths.

logging.basicConfig(format='%(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.expandvars(
    '$HOME/.config/transmission-process-torrents/config.yaml')
DATABASE_PATH = os.path.expandvars(
    '$HOME/.config/transmission-process-torrents/db.json')
DAY_SECONDS = datetime.timedelta(days=1).total_seconds()


class Command(object):

    def __init__(self, config_path=CONFIG_PATH, dry_run=False, remove=True):
        self.config_path = config_path
        self.dry_run = dry_run
        self.remove = remove

    def __call__(self):
        """
        Process or remove downloaded and orphaned torrents based on ratio and
        seed time.
        """

        link = hardlink.Command(dry_run=self.dry_run, force=True)

        # Load config.
        try:
            with open(self.config_path) as file:
                config = yaml.load(file.read())
        except Exception:
            self._err('Unable to load config: %s' % self.config_path)

        # Get JSON database for processed torrent status.
        database_path = config.get('db', DATABASE_PATH)
        logger.debug('Loading database: %s' % database_path)
        try:
            db = jsondict.JsonDict(database_path, autosave=True)
        except ValueError:
            self._err('Unable to load database: %s' % database_path)

        # Get mapped paths.
        mapped_paths = config.get('mapped_remote_paths', {}).items()

        # Get Transmission client.
        host = config.get('transmission_host', 'localhost')
        port = config.get('transmission_port', 9091)
        logger.debug('Connecting to Transmission: %s:%s' % (host, port))
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
            remote_path = os.path.join(
                torrent['downloadDir'], torrent['name'])

            # Get local path for remote path.
            local_path = self.get_local_path(remote_path, mapped_paths)

            # Find matching torrents directory.
            for dir_config in config['torrent_dirs']:

                # Get config for torrent directory.
                download_dir = dir_config['download_dir']
                post_processing_dir = dir_config['post_processing_dir']
                ratio = dir_config.get('ratio')
                seed_days = dir_config.get('seed_days')

                if local_path.startswith(download_dir):
                    found_torrents.add(local_path)

                    # Get downloaded and seeding status.
                    downloaded = bool(torrent['percentDone'] == 1)

                    # Get processed status.
                    processed = bool(downloaded and db.get(remote_path))

                    # Get seeding status.
                    seeding = bool(
                        ratio and
                        ratio > torrent['uploadRatio'] or
                        seed_days and
                        seed_days * DAY_SECONDS > torrent['secondsSeeding'])

                    # Hard link downloaded torrents to the post processing
                    # directory.
                    if downloaded and not processed:
                        logger.info('Processing torrent: %s' % local_path)
                        destination = os.path.join(
                            post_processing_dir,
                            os.path.relpath(local_path, download_dir),
                        )
                        link(local_path, destination)
                        if not self.dry_run:
                            db[remote_path] = True

                    # Remove processed torrents that have finished seeding.
                    elif processed and not seeding:
                        if not self.remove:
                            logger.info(
                                'Not removing inactive torrent: %s' %
                                torrent['name'])
                        else:
                            logger.info(
                                'Removing inactive torrent: %s' %
                                torrent['name'])
                            if not self.dry_run:
                                client(
                                    'torrent-remove',
                                    ids=[torrent['id']],
                                    delete_local_data=True,
                                )
                                del db[remote_path]

                    else:
                        # Ignore torrents that are still downloading or
                        # seeding.
                        logger.debug(
                            'Skipping active torrent: %s' % local_path)

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
                    '%s' % local_path)

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

                local_path = os.path.join(download_dir, path)

                # Find matching torrent for this path.
                for found_torrent in found_torrents:
                    if local_path.startswith(found_torrent):
                        # We found a match. No need to continue.
                        break

                # No matching torrent.
                else:

                    # Get remote path for local path.
                    remote_path = self.get_remote_path(
                        local_path, mapped_paths)

                    # Get processed status.
                    processed = db.get(remote_path, False)

                    # Hard link orphaned files that have not been processed.
                    if not processed:
                        logger.info(
                            'Processing orphaned file or directory: %s' %
                            local_path)
                        destination = os.path.join(
                            post_processing_dir,
                            os.path.relpath(local_path, download_dir),
                        )
                        link(local_path, destination)
                        # No need to add path to database, it would be removed
                        # immediately in the next code block.

                    # Remove orphaned files that have been processed.
                    logger.info(
                        'Removing orphaned file or directory: %s' %
                        local_path)
                    if not self.dry_run:
                        try:
                            shutil.rmtree(local_path)
                        except OSError:
                            os.remove(local_path)
                        # Remove path from database.
                        if remote_path in db:
                            del db[remote_path]

        # Remove stale records in database. Convert database keys to list to
        # avoid `RuntimeError: dictionary changed size during iteration`.
        for remote_path in list(db):

            # Get local path for remote path.
            local_path = self.get_local_path(remote_path, mapped_paths)

            # Remove from database.
            if not os.path.exists(local_path):
                logger.info(
                    'Removing stale record from database: %s' % remote_path)
                if not self.dry_run:
                    del db[remote_path]

    def _err(self, *args):
        """
        Log error and exit.
        """
        logger.error(*args)
        exit(1)

    def get_local_path(self, remote_path, mapped_paths, reverse=False):
        """
        Return mapped local path for given remote path.
        """
        for remote_prefix, local_prefix in mapped_paths:
            # Reverse. Return mapped remote path for given local path.
            if reverse:
                remote_prefix, local_prefix = local_prefix, remote_prefix
            if remote_path.startswith(remote_prefix):
                local_path = remote_path.replace(
                    remote_prefix, local_prefix)
                break
        else:
            local_path = remote_path
        return local_path

    def get_remote_path(self, local_path, mapped_paths):
        """
        Return mapped remote path for given local path.
        """
        return self.get_local_path(local_path, mapped_paths, reverse=True)


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
        '-R',
        '--no-remove',
        action='store_false',
        dest='remove',
        help='Do not remove processed torrents that have finished seeding.',
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
        Command(args.config, args.dry_run, args.remove)()
        # Restore standard output.
        sys.stdout = stdout

if __name__ == '__main__':
    main()
