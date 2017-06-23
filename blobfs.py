#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

# Copyright (C) 2017  Eddie Antonio Santos <easantos@ualberta.ca>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import atexit
import logging
import sqlite3
import time

from abc import ABC, abstractmethod
from errno import ENOENT, ENOTDIR, EBADF
from functools import wraps
from pathlib import Path, PurePosixPath
from stat import S_IFDIR, S_IFREG
from typing import Any, Callable, Dict, Iterator, Iterable, List, Union, cast

from fuse import FUSE, FuseOSError, LoggingMixIn, Operations  # type: ignore


Stat = Dict[str, Union[int, float]]


class LogExecute:
    """
    Logs calls to execute on a SQLite3 Connection object.
    """
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._instance = conn

    def execute(self, query, *args, **kwargs):
        logger = logging.getLogger(self.__class__.__name__)
        logger.debug("Query: %s", ' '.join(query.split()))
        logger.debug("Args: %r", args)
        return self._instance.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._instance, name)


class Entry(ABC):
    """
    Abstract. An entry in a directory.
    """
    @abstractmethod
    def stat(self) -> Stat: ...


class RegularFile(Entry):
    """
    Abstract. A regular file that can be used with read(2), write(2), etc.
    """
    @abstractmethod
    def read(self, size: int, offset: int, fh: int) -> bytes:
        """
        Read bytes from the file.
        """

    def stat(self) -> Stat:
        # Return a regular file with read permissions to everybody and ZERO
        # length!
        now = time.time()
        return dict(st_mode=(S_IFREG | 0o644),
                    st_nlink=1,
                    st_ctime=now,
                    st_mtime=now,
                    st_attime=now)


class Directory(Entry, Iterable[str]):
    """
    Abstract. A directory entry that can be used with readdir(3).
    """

    @abstractmethod
    def ls(self) -> Iterator[str]:
        """
        Returns all directory entries, except `.` and `..`.
        """

    def stat(self) -> Stat:
        # Return a directory with read and execute (traverse) permissions for
        # everybody.
        now = time.time()
        return dict(st_mode=(S_IFDIR | 0o755),
                    st_nlink=2,
                    st_ctime=now,
                    st_mtime=now,
                    st_attime=now)

    def __iter__(self) -> Iterator[str]:
        yield '.'
        yield '..'
        yield from self.ls()


class RootDirectory(Directory):
    """
    Root directory. Contains directories for each table.

    $ ls /
    table_1
    table_2
    ...
    table_n
    """

    def ls(self) -> Iterator[str]:
        rows = conn.execute(r"""
            SELECT name FROM sqlite_master
            WHERE type = 'table'
        """)
        for name, in rows:
            yield name


class TableDirectory(Directory):
    """
    A directory representing a table in the database. Each subdirectory is a
    row in the table named after its primary key (if possible). If the table
    does not have a suitable primary key, the rowid is used instead.

    $ ls /table_i/
    pk_1
    pk_2
    ...
    pk_n

    """
    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    @property
    def primary_key(self):
        """
        The effective primary key of this table.
        """

        rows = conn.execute(f"PRAGMA table_info({self.table_name})")
        # Constant column indices derived from the table_info() pragma.
        NAME = 1
        PK = 5

        pks = list(row[NAME] for row in rows if row[PK])
        # TODO: handle `WITHOUT ROWID` tables
        if len(pks) == 1:
            return pks[0]
        else:
            return 'rowid'

    def ls(self):
        rows = conn.execute(f"""
            SELECT {self.primary_key} FROM {self.table_name}
        """)
        for name, in rows:
            # TODO: ensure it's a valid filename
            yield str(name)


class RowDirectory(Directory):
    """
    A directory containing the contents of one row from a table.  Each
    subdirectory is a column.

    $ ls /table_i/row_j/
    col_1
    col_2
    ...
    col_3
    """
    def __init__(self, table_name: str, row_ref: str) -> None:
        # XXX: ensure `table_name` is valid
        self.table_name = table_name
        self.row_ref = row_ref

    def ls(self):
        rows = conn.execute(f"PRAGMA table_info({self.table_name})")
        NAME = 1
        for row in rows:
            yield row[NAME]


class ColumnFile(RegularFile):
    """
    A regular file which, when read, represents the contents of a column
    within a single row of a table. As written, this is intoned only for BLOB
    columns, however, it may be used for other data such as strings and simple
    NUMERIC data types.
    """
    def __init__(self, table_name, row_ref, column_name):
        # XXX: ensure `table_name` and `column_name` is valid
        self.table_name = table_name
        self.row_ref = row_ref
        self.column_name = column_name

    def stat(self) -> Stat:
        stat = super().stat()
        stat.update(st_size=self.size)  # type: ignore # Dict.update(**kwargs)
        return stat

    @property
    def size(self) -> int:
        """
        Determine the size of a blob.
        """
        # XXX: this only works for blobs...
        # XXX: it also HAPPENS to work for ASCII strings.
        rows = conn.execute(f"""
            SELECT length({self.column_name})
            FROM {self.table_name}
            WHERE {self.primary_key} = ?
        """, (self.row_ref,))
        (size,), = rows
        return int(size)

    @property
    def primary_key(self):
        # Delegate to the underlying table.
        return TableDirectory(self.table_name).primary_key

    def read(self, size: int, offset: int, fh: int) -> bytes:
        # Delegate to _read()
        return self._read()[offset:size + offset]

    def _read(self) -> bytes:
        """
        Reads the entire contents of the column. Regardless of the return
        type, it is returned the bytes object containing the full contents of
        the file.
        """
        rows = conn.execute(f"""
            SELECT {self.column_name}
            FROM {self.table_name}
            WHERE {self.primary_key} = ?
        """, (self.row_ref,))
        (content,), = rows

        if isinstance(content, bytes):
            return content
        else:
            return str(content).encode('UTF-8')


class BlobFS(LoggingMixIn, Operations):
    """
    Operations for the BlobFS FUSE filesystem.
    """

    # We do not implement these:
    access = None
    flush = None
    getxattr = None
    listxattr = None
    open = None
    opendir = None
    release = None
    releasedir = None
    statfs = None

    def _get_entry(self, path_str: str) -> Entry:
        """
        Gets an entry or raises ENOENT.
        """
        path = PurePosixPath(path_str)
        # TODO: assert things about the paths

        if len(path.parts) == 4:
            # Synthesize a file!
            _, table_name, row_ref, column_name = path.parts
            return ColumnFile(table_name, row_ref, column_name)
        elif len(path.parts) == 3:
            # It's a row!
            _, table_name, row_ref = path.parts
            return RowDirectory(table_name, row_ref)
        elif len(path.parts) == 2:
            # Table directory
            _, table_name = path.parts
            return TableDirectory(table_name)
        elif len(path.parts) == 1:
            # Root directory
            return RootDirectory()

        raise FuseOSError(ENOENT)

    def getattr(self, path: str, fh=None) -> Dict[str, Any]:
        "implement stat(2)"
        return self._get_entry(path).stat()

    def readdir(self, path: str, fs: int) -> List[str]:
        "return a list of all directory entries"
        entry = self._get_entry(path)
        if isinstance(entry, Directory):
            return list(entry)
        raise FuseOSError(ENOTDIR)

    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        "read bytes from the virtual file"
        entry = self._get_entry(path)
        if isinstance(entry, RegularFile):
            return entry.read(size, offset, fh)
        raise FuseOSError(EBADF)


if __name__ == '__main__':
    # Use exclusively for debugging purposes.
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=str, default='sources.sqlite3')
    parser.add_argument('mountpoint', type=str)
    args = parser.parse_args()
    conn = cast(sqlite3.Connection,
                LogExecute(sqlite3.connect(args.database)))
    fuse = FUSE(BlobFS(), args.mountpoint,
                foreground=True,
                ro=True,
                nothreads=True)
    atexit.register(lambda: conn.close())
