#!/usr/bin/env python
"""
Recursively hard link a source file or directory to a destination. Useful on
OS X, which doesn't support `cp -lR`.
"""

import errno
import os
import sys


def err(stderr):
    sys.stderr.write('%s\n' % stderr.strip())
    exit(1)


def makedirs(path):
    try:
        os.makedirs(path)
    except OSError as e:
        # Check if any intermediate path is a file. Don't complain if the
        # directory already exists.
        if e.errno not in (errno.EEXIST, errno.ENOTDIR):
            raise
        if not os.path.isdir(path):
            bits = os.path.split(path)
            bitpath = ''
            for bit in bits:
                bitpath = os.path.join(bitpath, bit)
                if not os.path.isdir(bitpath):
                    warn('hardlink: %s: Cannot replace file with directory' %
                         bitpath)
        return False
    return True


def hardlink(src, dst, force=False):
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)

    # Validate source.
    if not os.path.exists(src):
        err('hardlink: %s: No such file or directory' % src)

    # Merge directories, link files, overwrite existing files. We don't want to
    # leak hard links outside the destination. Replace directory symlinks with
    # directories, and file symlinks with hard links.
    if os.path.isdir(src):
        if os.path.isfile(dst):
            err('hardlink: %s: Cannot replace file with directory' % dst)
        cwd = os.getcwd()
        os.chdir(src)
        for local, dirs, files in os.walk('.', followlinks=True):
            # Directories.
            for d in dirs:
                dstpath = os.path.abspath(os.path.join(dst, local, d))
                if os.path.isdir(dstpath) and os.path.islink(dstpath):
                    os.remove(dstpath)
                makedirs(dstpath)
            # Files.
            for f in files:
                srcfile = os.path.realpath(
                    os.path.abspath(os.path.join(local, f)))
                dstfile = os.path.abspath(os.path.join(dst, local, f))
                if not os.path.exists(srcfile):
                    warn('hardlink: %s: No such file or directory' % srcfile)
                    continue
                if srcfile == dstfile:
                    warn('hardlink: %s: Cannot link file to itself' % srcfile)
                    continue
                if os.path.isdir(dstfile):
                    warn('hardlink: %s: Cannot replace directory with file'
                         % dstfile)
                    continue
                if os.path.isfile(dstfile) and os.path.islink(dstfile):
                    os.remove(dstfile)
                makedirs(os.path.dirname(dstfile))
                link(srcfile, dstfile, force)
        os.chdir(cwd)

    # Link files.
    if os.path.isfile(src):
        if os.path.isdir(dst):
            err('hardlink: %s: Cannot replace directory with file' % dst)
        makedirs(os.path.dirname(dst))
        link(src, dst, force)


def link(src, dst, force=False):
    try:
        os.link(src, dst)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
        if force:
            os.remove(dst)
            try:
                os.link(src, dst)
            except:
                print os.path.realpath(src), dst
                raise
        else:
            warn('hardlink: %s: Already exists' % dst)


def main():
    if len(sys.argv) not in [3, 4]:
        err('Usage: %s <src> <dst> [force]' % os.path.basename(sys.argv[0]))
    hardlink(*sys.argv[1:])


def warn(stderr):
    sys.stderr.write('%s\n' % stderr.strip())


if __name__ == '__main__':
    main()
