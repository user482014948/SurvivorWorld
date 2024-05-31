from setuptools import setup, find_packages
import os
import re

from src import __version__

base_game_install_reqs = ['jupyter', 'graphviz']

with open("README.md", "r") as fh:
    long_description = fh.read()

with open(os.path.join(os.path.dirname(__file__), "requirements.txt"), 'r') as reqs:
    install_packages = [req for req in reqs.read().split('\n') if not re.match(r"#\s?", req) and req]
    install_packages.extend(base_game_install_reqs)

setup(
    name='src',
    version=__version__,
    author='none',
    author_email='none',
    description='Outwit, Outplay, Out-Generate: A Framework for Designing Strategic Generative Agents in Competitive Environments',
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    include_package_data=True,
    install_requires=install_packages,
    extras_require={
        'dev': [
            'black',
            'nbformat'
        ],
    },
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ]
)
