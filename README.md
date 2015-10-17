# Overview

This package provides a `process-torrents` command that will automatically hard
link downloaded torrents to a post processing directory and finally remove the
torrent once ratio and seed time requirements have been satisfied.

This allows 3rd party program like [CouchPotato] and [SickRage] to then move
the files from the post processing directory, without removing the torrent from
Transmission.

# Installation

Clone the repository and install into a [virtualenv] with `pip`:

    (venv)$ git clone http://mrmachine.net/transmission-process-torrents.git
    (venv)$ pip install -r transmission-process-torrents/requirements.txt

# Configuration

Copy the [config-sample.yaml] file to
`~/.config/transmission-process-torrents/config.yaml` and edit to suit your
needs.

Configuration is needed to tell the script:

  * How to connect to Transmission.
  * Where Transmission is saving downloaded torrents.
  * Where to hard link downloaded files for post processing.
  * When to remove a torrent, according to ratio and seed time rules.

See the comments in the sample file for more information.

# Usage

Just run the `process-torrents` command:

    (venv)$ process-torrents

[config-sample.yaml]: config-sample.yaml
[CouchPotato]: https://github.com/RuudBurger/CouchPotatoServer
[SickRage]: https://github.com/SiCKRAGETV/SickRage
[virtualenv]: https://virtualenv.pypa.io/en/latest/
