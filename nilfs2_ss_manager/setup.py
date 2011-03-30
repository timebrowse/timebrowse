from setuptools import setup
import sys

setup(
  name = 'nilfs2_ss_manager',
  version = '0.6',
  author = 'Jiro SEKIBA',
  author_email = 'jir@unicus.jp',
  py_modules = ['nilfs2'],
  scripts = ['nilfs2_ss_manager'],
  description = 'nilfs2 snapshot manager',
  data_files = [('/etc', ['nilfs_ss.conf'])]
)
