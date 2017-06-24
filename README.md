BlobFS proof of concept
=======================

BlobFS is a [FUSE] filesystem that lets you access fields in an SQLite3
database with the convenience of a regular file system.

Inspired by the news that accessing blobs from SQLite3 can be [around
35% faster than from the filesystem][fasterthanfs], BlobFS is meant to
be a way of accessing that same data—locked away as a `BLOB` in the
database—with your favourite software that reads conventional files.

BlobFS is proof of concept software. As such, it is lacking in security,
reliability, speed, and testing. For more information, see
[Limitations](#limitations).

[fasterthanfs]: https://www.sqlite.org/fasterthanfs.html
[FUSE]: https://github.com/libfuse/libfuse


Install
-------

You need Python 3.6 and [fusepy]. You can install the latter using pip:

    python3.6 -m pip install fusepy

[fusepy]: https://github.com/terencehonles/fusepy


Usage
-----

    blobfs <database> <mountpoint>

Mount an SQLite3 `<database>` on the provided empty directory
`<mountpoint>`.

### Example

Say you want to mount the database called `sources.sqlite3`. This
database contains Python source code downloaded from GitHub and has the
following schema:

```sql
CREATE TABLE repository (
    owner, name,
    PRIMARY KEY (owner, name)
);

CREATE TABLE source_file (
    hash PRIMARY KEY,
    source BLOB NOT NULL
);

CREATE TABLE repository_source (
    owner, name, hash, path,
    PRIMARY KEY (owner, name, hash, path)
);
```

Create a new directory for the mount called `mnt/`.

    $ mkdir mnt
    $ ls -F
    blobfs.py
    mnt/
    sources.sqlite3

Run the FUSE filesystem in the foreground.

    $ ./blobfs.py sources.sqlite3 mnt/
    <A whole wacktonne of log messages from FUSE>

Now switch to a different terminal (or use your file manager!) and
navigate into the newly mounted filesystem.

The root directory contains subdirectories for each table:

    $ ls -F mnt/
    repository/
    source_file/
    repository_source/

Within a table directory are subdirectories for every row in that table.

    $ cd mnt/source_file
    $ ls -F
    98c2d41c472c435aa3d06180a626f1690b681fb07499e3f633a85007f25bed18/

Within the directory for a row in table is a regular file for all
fields. You may then access any field as a regular file. Blobs are read
verbatim, and while other data types are converted to strings, and then
encoded in UTF-8. Here, the field `source` is a blob containing Python
source code.

    $ cd 98c2d41c472c435aa3d06180a626f1690b681fb07499e3f633a85007f25bed18/
    $ ls
    hash
    source
    $ wc source
         331    1066    9567 source
    $ file source
    source: a python3 script text executable
    $ python3 source --help
    usage: source [-h] database mountpoint

    positional arguments:
      database
      mountpoint

    optional arguments:
      -h, --help  show this help message and exit

In summary, mounting this database has created the following file
structure:

```
.
├── repository
│   └── 1
│       ├── name
│       └── owner
├── repository_source
│   └── 1
│       ├── hash
│       ├── name
│       ├── owner
│       └── path
└── source_file
    └── 98c2d41c472c435aa3d06180a626f1690b681fb07499e3f633a85007f25bed18
        ├── hash
        └── source
```


Limitations
-----------

This proof of concept is vulnerable to SQL injection, as it does not
validate that the table names and primary keys have sanitary names.
Additionally, it does not validate that names stored in the database
make for reasonable filenames—filenames beginning with `-`, `.`, or
containing `/`, or `\0` anywhere are examples of unreasonable filenames.

Additionally, every system call often implies several database queries.
No database queries are ever cached, and related queries are never run
within a transaction.  Additionally, several high-level operations (such
as `ls -l`) require numerous system calls, degrading performance
significantly.

Since `readdir(3)` is implemented by copying the name of each primary
key into memory and returning then all as one big list, it is a quite
inefficient operation, and is incapable of being interrupted. As such,
running `ls` in large table (over 500 thousand rows) will usually fail,
due to timeouts.

This script runs the FUSE filesystem in foreground mode and in one
thread. A practical implementation would be capable of running in the
background, and would be thread-safe.


Copying
-------

Licensed under the terms of the GPLv3 license. See [LICENSE].

[LICENSE]: ./LICENSE
