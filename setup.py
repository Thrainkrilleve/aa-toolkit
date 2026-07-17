import os
from setuptools import find_packages, setup

from aa_admin_toolkit import __version__

# read the contents of your README file
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name="aa-admin-toolkit",
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    license="MIT",
    description="Admin Toolkit for Alliance Auth to run management commands from UI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Thrainkrilleve/aa-admin-toolkit",
    author="Thrain Krilleve",
    author_email="thrain@example.com",
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Django",
        "Framework :: Django :: 4.0",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
    install_requires=[
        "allianceauth>=3.0.0",
    ],
)
