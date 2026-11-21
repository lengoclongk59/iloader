from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-iloader",
    version="1.0.0",
    description="Agent-friendly CLI harness for the iloader sideloader",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    package_data={"cli_anything.iloader": ["skills/*.md", "*.md"]},
    install_requires=["click>=8.0.0", "prompt-toolkit>=3.0.0", "truststore>=0.9"],
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "cli-anything-iloader=cli_anything.iloader.iloader_cli:main",
        ],
    },
    python_requires=">=3.10",
)
