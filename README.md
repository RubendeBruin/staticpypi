# staticpypi
maintain a pypi compatible index on a static server

## Purpose

The purpose is to enable deploying python .whl files on a static server such that they can be installed using tools like pip.

The proposed setup is a desktop client that manages the contents of the server via ftp and updates it whenever publishing a new package.

The desktop application will 

- connect with a FTP server using user-provided credentials and url
- gather the existing whl files
- add the whl file(s) to be added
- upload the newly added whl files
- create/update all other required files on the server



the result is a directory and file structure that can be served over http(s).



In a typical configuration, access to the repository over https in protected using .htaccess



## Framework

Use python

Use PySide6 for the ui

use the settings module from pyside6 for storing url, username etc.



## References

Look at existing the simplepypi pypi package. 

Look at the PEP specification



