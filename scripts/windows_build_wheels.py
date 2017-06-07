
import errno
import json
import os
import shutil
import tempfile
import textwrap

from contextlib import contextmanager
from functools import wraps
from subprocess import check_call, check_output


SCRIPT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
STANDALONE_DIR = os.path.join(ROOT_DIR, "standalone-build")

print("SCRIPT_DIR: %s" % SCRIPT_DIR)
print("ROOT_DIR: %s" % ROOT_DIR)
print("STANDALONE_DIR: %s" % STANDALONE_DIR)


def mkdir_p(path):
    """Ensure directory ``path`` exists. If needed, parent directories
    are created.

    Adapted from http://stackoverflow.com/a/600612/1539918
    """
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:  # pragma: no cover
            raise


@contextmanager
def push_env(**kwargs):
    """This context manager allow to set/unset environment variables.
    """
    saved_env = dict(os.environ)
    for var, value in kwargs.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]
    yield
    os.environ.clear()
    for (saved_var, saved_value) in saved_env.items():
        os.environ[saved_var] = saved_value


class ContextDecorator(object):
    """A base class or mixin that enables context managers to work as
    decorators."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __enter__(self):
        # Note: Returning self means that in "with ... as x", x will be self
        return self

    def __exit__(self, typ, val, traceback):
        pass

    def __call__(self, func):
        @wraps(func)
        def inner(*args, **kwds):  # pylint:disable=missing-docstring
            with self:
                return func(*args, **kwds)
        return inner


class push_dir(ContextDecorator):
    """Context manager to change current directory.
    """
    def __init__(self, directory=None, make_directory=False):
        """
        :param directory:
          Path to set as current working directory. If ``None``
          is passed, ``os.getcwd()`` is used instead.

        :param make_directory:
          If True, ``directory`` is created.
        """
        self.directory = None
        self.make_directory = None
        self.old_cwd = None
        super(push_dir, self).__init__(
            directory=directory, make_directory=make_directory)

    def __enter__(self):
        self.old_cwd = os.getcwd()
        if self.directory:
            if self.make_directory:
                mkdir_p(self.directory)
            os.chdir(self.directory)
        return self

    def __exit__(self, typ, val, traceback):
        os.chdir(self.old_cwd)


def pip_install(python_dir, package):
    pip = os.path.join(python_dir, "Scripts", "pip.exe")
    print("Installing $package using %s" % pip)
    check_call([pip, "install", package])


def prepare_build_env(python_version):
    python_dir = "C:/Python%s" % python_version
    if not os.path.exists(python_dir):
        raise FileNotFoundError("Aborting. python_dir [%s] does not exist." % python_dir)

    venv = os.path.join(python_dir, "Scripts", "virtualenv.exe")
    venv_dir = os.path.join(ROOT_DIR, "venv-%s" % python_version)
    print("Creating python virtual environment: %s" % venv_dir)
    if not os.path.exists(venv_dir):
        check_call([venv, venv_dir])
    pip_install(venv_dir, "scikit-build")


def build_wheel(python_version, single_wheel=False):
    venv_dir = os.path.join(ROOT_DIR, "venv-%s" % python_version)

    python_executable = os.path.join(venv_dir, "Scripts", "python.exe")
    python_include_dir = os.path.join(venv_dir, "Include")

    # XXX It should be possible to query skbuild for the library dir associated
    #     with a given interpreter.
    xy_ver = python_version.split("-")[0]

    python_library = "C:/Python%s/libs/python%s.lib" % (python_version, xy_ver)

    print("")
    print("PYTHON_EXECUTABLE: %s" % python_executable)
    print("PYTHON_INCLUDE_DIR: %s" % python_include_dir)
    print("PYTHON_LIBRARY: %s" % python_library)

    pip = os.path.join(venv_dir, "Scripts", "pip.exe")

    ninja_executable = os.path.join(ROOT_DIR, "venv-27-x64", "Scripts", "ninja.exe")
    print("NINJA_EXECUTABLE:%s" % ninja_executable)

    # Update PATH
    path = os.path.join(venv_dir, "Scripts")
    with push_env(PATH="%s:%s" % (path, os.environ["PATH"])):

        # Install dependencies
        check_call([pip, "install",
                    "-r", os.path.join(ROOT_DIR, "requirements-dev.txt")])

        build_type = "Release"
        source_path = "%s/ITK-source" % STANDALONE_DIR
        build_path = "C:/P/IPP/ITK-win_%s" % python_version
        setup_py_configure = os.path.join(
            SCRIPT_DIR, "..", "setup_py_configure.py")

        # Clean up previous invocations
        if os.path.exists(build_path):
            shutil.rmtree(build_path)

        if single_wheel:

            print("#")
            print("# Build single ITK wheel")
            print("#")

            # Configure setup.py
            check_call([python_executable, setup_py_configure, "itk"])

            # Generate wheel
            check_call([
                python_executable,
                "setup.py", "bdist_wheel",
                "--build-type", build_type, "-G", "Ninja",
                "--",
                "-DCMAKE_MAKE_PROGRAM:FILEPATH=%s" % ninja_executable,
                "-DITK_SOURCE_DIR:PATH=%s" % source_path,
                "-DITK_BINARY_DIR:PATH=%s" % build_path,
                "-DPYTHON_EXECUTABLE:FILEPATH=%s" % python_executable,
                "-DPYTHON_INCLUDE_DIR:PATH=%s" % python_include_dir,
                "-DPYTHON_LIBRARY:FILEPATH=%s" % python_library
            ])
            # Cleanup
            check_call([python_executable, "setup.py", "clean"])

        else:

            print("#")
            print("# Build multiple ITK wheels")
            print("#")

            try:
                # Because of python issue #14243, we set "delete=False" and
                # delete manually after process execution.
                script_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".py")
                script_file.write(bytearray(textwrap.dedent(
                    """
                    import json
                    from skbuild.platform_specifics.windows import WindowsPlatform
                    # Instantiate
                    build_platform = WindowsPlatform()
                    generator = build_platform.default_generators[0]
                    assert generator.name == "Ninja"
                    print(json.dumps(generator.env))
                    """  # noqa: E501
                ), "utf-8"))
                script_file.file.flush()
                output = check_output([python_executable, script_file.name])
                build_env = json.loads(output.decode("utf-8").strip())
            finally:
                script_file.close()
                os.remove(script_file.name)

            py_site_packages_path = os.path.join(
                SCRIPT_DIR, "..", "_skbuild", "cmake-install")

            # Build ITK python
            with push_dir(directory=build_path, make_directory=True), \
                    push_env(**build_env):

                check_call([
                    "cmake",
                    "-DCMAKE_BUILD_TYPE:STRING=%s" % build_type,
                    "-DITK_SOURCE_DIR:PATH=%s" % source_path,
                    "-DITK_BINARY_DIR:PATH=%s" % build_path,
                    "-DBUILD_TESTING:BOOL=OFF",
                    "-DPYTHON_EXECUTABLE:FILEPATH=%s" % python_executable,
                    "-DPYTHON_INCLUDE_DIR:PATH=%s" % python_include_dir,
                    "-DPYTHON_LIBRARY:FILEPATH=%s" % python_library,
                    "-DWRAP_ITK_INSTALL_COMPONENT_IDENTIFIER:STRING=PythonWheel",
                    "-DWRAP_ITK_INSTALL_COMPONENT_PER_MODULE:BOOL=ON",
                    "-DPY_SITE_PACKAGES_PATH:PATH=%s" % py_site_packages_path,
                    "-DITK_LEGACY_SILENT:BOOL=ON",
                    "-DITK_WRAP_PYTHON:BOOL=ON",
                    "-DITK_WRAP_PYTHON_LEGACY:BOOL=OFF",
                    "-G", "Ninja",
                    source_path
                ])
                check_call([ninja_executable])

            # Build wheels
            with open(os.path.join(SCRIPT_DIR, "..", "WHEEL_NAMES.txt"), "r") as content:
                wheel_names = content.readline()

            for wheel_name in wheel_names:
                # Configure setup.py
                check_call([
                    python_executable, setup_py_configure, wheel_name])

                # Generate wheel
                check_call([
                    python_executable,
                    "setup.py", "bdist_wheel",
                    "--build-type", build_type, "-G", "Ninja",
                    "--",
                    "-DITK_SOURCE_DIR:PATH=%s" % source_path,
                    "-DITK_BINARY_DIR:PATH=%s" % build_path,
                    "-DITKPythonPackage_ITK_BINARY_REUSE:BOOL=ON",
                    "-DITKPythonPackage_WHEEL_NAME:STRING=%s" % wheel_name,
                    "-DPYTHON_EXECUTABLE:FILEPATH=%s" % python_executable,
                    "-DPYTHON_INCLUDE_DIR:PATH=%s" % python_include_dir,
                    "-DPYTHON_LIBRARY:FILEPATH=%s" % python_library
                ])

                # Cleanup
                check_call([python_executable, "setup.py", "clean"])

        # Remove unnecessary files for building against ITK
        for root, _, file_list in os.walk(build_path):
            for filename in file_list:
                extension = os.path.splitext(filename)[1]
                if extension in [".cpp", ".xml", ".obj"]:
                    os.remove(os.path.join(root, filename))

        shutil.rmtree(os.path.join(build_path, "Wrapping", "Generators"))
        # XXX
        # Remove-Item -Recurse -Force $build_path\\Wrapping\\Generators\\castxml*


def build_wheels():

    prepare_build_env("27-x64")
    prepare_build_env("35-x64")
    prepare_build_env("36-x64")

    with push_dir(directory=STANDALONE_DIR, make_directory=True):

        cmake_executable = "cmake.exe"
        tools_venv = os.path.join(ROOT_DIR, "venv-27-x64")
        pip_install(tools_venv, "ninja")
        ninja_executable = os.path.join(tools_venv, "Scripts", "ninja.exe")

        # Build standalone project and populate archive cache
        check_call([
            cmake_executable,
            "-DITKPythonPackage_BUILD_PYTHON:PATH=0",
            "-G", "Ninja",
            "-DCMAKE_MAKE_PROGRAM:FILEPATH=%s" % ninja_executable,
            ROOT_DIR
        ])

        check_call([ninja_executable])

    single_wheel = False

    # Compile wheels re-using standalone project and archive cache
    build_wheel("27-x64", single_wheel=single_wheel)
    build_wheel("35-x64", single_wheel=single_wheel)
    build_wheel("36-x64", single_wheel=single_wheel)


if __name__ == "__main__":
    build_wheels()
