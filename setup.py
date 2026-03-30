from setuptools import setup, find_packages

setup(
    name="su2-wizard",
    version="0.1.0",
    description="Interactive CLI wizard for generating SU2 CFD configuration files",
    author="Ahmed",
    packages=find_packages(),
    package_data={"": ["data/*.yaml"]},
    include_package_data=True,
    install_requires=[
        "questionary>=2.0.0",
        "rich>=13.0.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "su2-wizard=main:main",
        ],
    },
    python_requires=">=3.10",
)
