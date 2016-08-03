#!/usr/bin/env python

from distutils.core import setup

setup(
    name='Nervesync',
    version='0.0.1',
    description='A nasty little utility that allows you to use Nerve in a way that it currently can\'t be used.',
    author='Kennedy Brown',
    packages=['nervesync'],
    install_requires=open("requirements.txt", "r").readlines(),
    scripts=['bin/nervesync'],
    #entry_points = {
    #    'console_scripts': [
    #        'nervesync = nervesync.__main__',
    #    ]
    #},
)
