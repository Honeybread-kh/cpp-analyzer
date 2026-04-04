from setuptools import setup, find_packages

setup(
    name="cpp_analyzer",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "libclang>=16.0.0",
        "click>=8.0.0",
        "rich>=13.0.0",
        "networkx>=3.0",
        "PyYAML>=6.0",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "cpp-analyzer=cpp_analyzer.cli.commands:cli",
        ],
    },
    python_requires=">=3.9",
)
