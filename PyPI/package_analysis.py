#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Analysis of Python packages."""

import json
import os
from os import walk
import pymysql.cursors
import re
import tarfile
import logging
import sys

if sys.version_info[0] == 2:
    from urllib import urlretrieve
else:
    from urllib.request import urlretrieve

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG,
                    stream=sys.stdout)


def main(package_name, package_url):
    """
    Parameters
    ----------
    package_name : str
    package_url : str
        Path to a Python package.
    """
    pkg_name = package_name
    filepaths = download(package_url)
    with open("secret.json") as f:
        mysql = json.load(f)
    package_id = get_pkg_id_by_name(pkg_name, mysql)
    if package_id is None:
        logging.info("Package id could not be determined")
        sys.exit(1)
    required_packages = get_requirements(filepaths, pkg_name)
    imported_packages = get_imports(filepaths, pkg_name)
    setup_packages = get_setup_packages(filepaths, pkg_name)
    store_dependencies(mysql,
                       package_id,
                       required_packages,
                       imported_packages,
                       setup_packages)


def store_dependencies(mysql,
                       package_id,
                       required_packages,
                       imported_packages,
                       setup_packages):
    """
    Parameters
    ----------
    mysql : dict
        MySQL database connection information
    package_id : int
    required_packages : list
    imported_packages : list
    setup_packages : list
    """
    connection = pymysql.connect(host=mysql['host'],
                                 user=mysql['user'],
                                 passwd=mysql['passwd'],
                                 db=mysql['db'],
                                 cursorclass=pymysql.cursors.DictCursor,
                                 charset='utf8')

    insert_dependency_db(imported_packages,
                         'imported',
                         package_id,
                         mysql,
                         connection)
    insert_dependency_db(required_packages,
                         'requirements.txt',
                         package_id,
                         mysql,
                         connection)
    insert_dependency_db(setup_packages,
                         'setup.py',
                         package_id,
                         mysql,
                         connection)


def insert_dependency_db(imported_packages,
                         req_type,
                         package_id,
                         mysql,
                         connection):
    """
    Parameters
    ----------
    imported_packages : list
    req_type : str
        'setup.py', 'requirements.txt' or 'imported'
    package_id : int
    mysql : dict
        credentials for the connection
    connection : pymysql connection object
    """
    cursor = connection.cursor()
    for pkg, times in imported_packages.items():
        package_info = {'package': package_id,
                        'needs_package': get_pkg_id_by_name(pkg, mysql),
                        'times': times,
                        'req_type': req_type}
        if package_info['needs_package'] is not None:
            try:
                sql = ("INSERT INTO `dependencies` "
                       "(`package`, `needs_package`, `req_type`, `times`) "
                       " VALUES "
                       "('{package}', '{needs_package}', '{req_type}', "
                       "'{times}');").format(
                    **package_info)
                cursor.execute(sql)
                connection.commit()
            except pymysql.err.IntegrityError as e:
                if 'Duplicate entry' not in str(e):
                    logging.warning(e)
        else:
            logging.info("Package '%s' was not found. Skip.", pkg)


def get_pkg_id_by_name(pkg_name, mysql):
    """
    Parameters
    ----------
    pkg_name : str
    mysql : dict
        MySQL database connection information

    Returns
    -------
    int or None
    """
    connection = pymysql.connect(host=mysql['host'],
                                 user=mysql['user'],
                                 passwd=mysql['passwd'],
                                 db=mysql['db'],
                                 cursorclass=pymysql.cursors.DictCursor,
                                 charset='utf8')
    cursor = connection.cursor()
    sql = "SELECT id FROM `packages` WHERE `name` = %s"
    cursor.execute(sql, (pkg_name, ))
    id_number = cursor.fetchone()
    if id_number is not None and 'id' in id_number:
        return id_number['id']
    else:
        return None


def get_pkg_extension(package_url):
    """
    Parameters
    ----------
    package_url : str

    Returns
    -------
    str
        File extension of the package given by url
    """
    if package_url.endswith(".tar.gz"):
        return ".tar.gz"
    elif package_url.endswith(".whl"):
        return ".whl"
    else:
        raise NotImplementedError()


def download(package_url):
    """
    Parameters
    ----------
    package_url : str
        URL of a Python package

    Returns
    -------
    list
        Paths to all unpackaged files
    """
    file_ending_len = len(get_pkg_extension(package_url))

    # TODO: What about .whl
    target_dir = "pypipackages"
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    pkg_name = os.path.basename(package_url)
    target = os.path.join(target_dir, pkg_name)

    if not os.path.exists(target):
        urlretrieve(package_url, target)
        logging.info("Package '%s' downloaded.", pkg_name)
    else:
        logging.info("Package '%s' was already downloaded.", pkg_name)

    if not os.path.exists(target[:-file_ending_len]):
        if package_url.endswith("tar.gz"):
            with tarfile.open(target) as tar:
                tar.extractall(target[:-file_ending_len])
        elif package_url.endswith(".whl"):
            import zipfile
            with zipfile.ZipFile(target) as tar:
                tar.extractall(target[:-file_ending_len])
        else:
            raise NotImplementedError

    filepaths = []
    for (dirpath, dirnames, filenames) in walk(target[:-file_ending_len]):
        filepaths.extend([os.path.join(dirpath, f) for f in filenames])
    return filepaths


def get_requirements(filepaths, pkg_name):
    """
    Get a list of all "officially" set requirements.

    Parameters
    ----------
    filepaths : list
        Paths to files of a package
    pkg_name : str
        Name of the currently parsed package.

    Returns
    -------
    list
        "Officially" set requirements
    """
    imports = {}
    requirements_file = [f for f in filepaths
                         if f.endswith("requirements.txt")]

    if len(requirements_file) > 0:
        requirements_file = requirements_file[0]
        logging.info(requirements_file)
        # TODO: parse requirements.txt
    else:
        logging.debug("Package '%s' has no requirements.txt.",
                      pkg_name)
    return imports


def get_imports(filepaths, pkg_name):
    """
    Get a list of all imported packages.

    Parameters
    ----------
    filepaths : list
        Paths to files of a package
    pkg_name : str
        Name of the currently parsed package.

    Returns
    -------
    dict
        Names of packages which got imported and how often
    """
    # TODO: Not all python files end with .py. We loose some.
    filepaths = [f for f in filepaths if f.endswith(".py")]
    simple_pattern = re.compile("^\s*import\s+([a-zA-Z][a-zA-Z0-9_]*)",
                                re.MULTILINE)
    from_pattern = re.compile("^\s*from\s+import\s+([a-zA-Z][a-zA-Z0-9_]*)",
                              re.MULTILINE)
    imports = {}
    for filep in filepaths:
        with open(filep) as f:
            content = f.read()

        imported = (simple_pattern.findall(content) +
                    from_pattern.findall(content))
        for import_pkg_name in imported:
            if import_pkg_name in imports:
                imports[import_pkg_name] += 1
            else:
                imports[import_pkg_name] = 1
    return imports


def get_setup_packages(filepaths, pkg_name):
    """
    Get a list of all imported packages.

    Parameters
    ----------
    filepaths : list
        Paths to files of a package
    pkg_name : str
        Name of the currently parsed package.

    Returns
    -------
    dict
        Names of packages which got imported and how often
    """
    setup_py_file = [f for f in filepaths if f.endswith("setup.py")]
    imports = {}
    if len(setup_py_file) > 0:
        setup_py_file = setup_py_file[0]
        logging.info(setup_py_file)
        # TODO: parse setup.py
        # can be dangerous
        # look for 'install_requires'
        # ... may the force be with you
    else:
        logging.debug("Package '%s' has no setup.py.",
                      pkg_name)
    return imports


def get_parser():
    """The parser object for this script."""
    from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
    parser = ArgumentParser(description=__doc__,
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("--name",
                        dest="name",
                        help="name of the package",
                        required=True)
    parser.add_argument("-p", "--package_url",
                        dest="package_url",
                        help="url where the package is",
                        required=True)
    return parser


if __name__ == "__main__":
    args = get_parser().parse_args()
    main(args.name, args.package_url)