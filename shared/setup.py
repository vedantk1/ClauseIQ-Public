from setuptools import find_packages, setup


setup(
    name="shared",
    version="1.0.0",
    packages=find_packages(),
    description="Shared types for ClauseIQ frontend and backend",
    license="MIT",
    install_requires=[
        "pydantic>=2.0.0",
    ],
)
