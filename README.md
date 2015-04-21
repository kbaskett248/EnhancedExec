# EnhancedExec

A [Sublime Text 3](http://www.sublimetext.com/) package that enhances the built-in Exec command, adding a few useful features.

## Features

*   Drop-in replacement for Exec. You can replace the calls to 'exec' in any build system or command with a call to 'enhanced_exec'.
*   EnhancedExec provides the following additional features:
    *   Can read results from a results file in addition to STDOUT and STDERR.
    *   Can disable setting startupinfo on windows.
    *   Can specify that the called process should finish before returning.
    *   Can specify an initial message to put in the build window

# Installation

## Package Control

Install [Package Control](http://wbond.net/sublime_packages/package_control). Add this repository (https://bitbucket.org/kbaskett/enhancedexec) to Package Control. EnhancedExec will show up in the packages list.

## Manual installation

Go to the "Packages" directory (`Preferences` > `Browse Packages…`). Then download or clone this repository:

https://bitbucket.org/kbaskett/enhancedexec.git

