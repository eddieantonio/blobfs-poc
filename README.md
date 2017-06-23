BlobFS proof of concept
=======================

BlobFS is a [FUSE] filesystem that lets you access fields in an SQLite3
database with the convenience of regular file system.

Inspired by the news that accessing blobs from SQLite3 can be [around
35% faster than from the filesystem][fasterthanfs], BlobFS is meant to
be a way of accessing that same data, locked away as a `BLOB` in the
database with software that reads conventional files.

BlobFS is proof of concept software. As such, it is lacking in
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

Usage:

    blobfs <database> <mountpoint>

Mount an SQLite3 `<database>` on the provided empty directory
`<mountpoint>`.

### Example

Mounting the database called `sources.sqlite3`. This database contains
Python source code downloaded from GitHub and has the following schema:

```sql
CREATE TABLE repository (
    owner VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    PRIMARY KEY (owner, name)
);

CREATE TABLE source_file (
    hash VARCHAR NOT NULL,
    source BLOB NOT NULL,
    PRIMARY KEY (hash)
);

CREATE TABLE repository_source (
    owner VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    hash VARCHAR NOT NULL,
    path VARCHAR NOT NULL,
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
navigate the newly mounted filesystem!

The first directory are all of the tables.

    $ ls -F mnt/
    repository/
    source_file/
    repository_source/

Within a table directory is a subdirectory for every row in that table.

    $ cd mnt/source_file
    $ ls -F
    98c2d41c472c435aa3d06180a626f1690b681fb07499e3f633a85007f25bed18/

Within the directory for a row in table is a regular file for all
fields. You may then access any field as a regular file. Blobs are read
verbatim.

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

A tree view of what mounting this database has done:

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

The proof of concept is vulnerable to SQL injection, as it does not
validate that the table names and primary keys have valid names.
Additionally, it does not validate that names that come from the
database make for reasonable filenames---filenames beginning with `-`,
`.`, or containing `/`, or `\0` anywhere in the entry name are examples
of unreasonable filenames.

Additionally, every system call often implies several database queries.
No database queries are ever cached. Additionally, several high-level
operations (such as `ls -l`) require numerous system calls, degrading
performance significantly.

Since `readdir(3)` is implemented by copying the name of each primary
key into memory and returning as one list, it is quite inefficient, and
incapable of being interrupted. As such, running `ls` in large table
(over 500 thousand rows) will usually fail, due to timeouts.

This script runs the FUSE filesystem in foreground mode and on one
thread. A practical implementation would be capable of running in the
background, and would be thread-safe.


Copying
-------

Licensed under the terms of the GPLv3 license. See [LICENSE].

[LICENSE]: ./LICENSE
