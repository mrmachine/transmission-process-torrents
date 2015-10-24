# Overview

This package provides a `process-torrents` command that hard links downloaded
torrents to a post processing directory and removes them once ratio and seed
time requirements have been satisfied.

This allows 3rd party programs to then process and remove files from the post
processing directory, without impacting torrents that are still seeding.

# Installation

Install from PyPI with `pip`:

    $ pip install transmission-process-torrents

# Configuration

Create and edit a config file from the sample:

    $ mkdir -p ~/.config/transmission-process-torrents
    $ process-torrents -s > ~/.config/transmission-process-torrents/config.yaml

Configuration includes:

  * How to connect to Transmission.
  * Where Transmission is saving downloaded torrents.
  * Where to hard link downloaded torrents for post processing.
  * When to remove torrents, by ratio and seed time.

Multiple download and post processing directories can be configured, each with
their own ratio and seed time. See the comments in the sample file for more
information.

# Usage

Via the command line script:

    $ process-torrents -h
    usage: process-torrents [-h] [-c PATH] [-d] [-q] [-s] [-v]

    Hard link downloaded torrents to a post processing directory. Remove processed
    torrents that have satisfied their ratio and seed time requirements.

    optional arguments:
      -h, --help            show this help message and exit
      -c PATH, --config PATH
                            path to config file
      -d, --dry-run         simulate results
      -q, --quiet           silence standard output
      -s, --sample-config   dump sample config to standard output
      -v, --verbose         increase verbosity of standard output for each
                            occurrence, e.g. -vv
