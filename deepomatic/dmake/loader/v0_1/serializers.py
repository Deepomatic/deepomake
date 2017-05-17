import os
import copy
import json
import random
from deepomatic.dmake.serializer import ValidationError, FieldSerializer, YAML2PipelineSerializer
import deepomatic.dmake.common as common
from deepomatic.dmake.common import DMakeException

###############################################################################

def generate_copy_command(commands, tmp_dir, src):
    src = common.join_without_slash(src)
    if src == '':
        src = '.'
    dst = os.path.join(tmp_dir, 'app', src)
    sub_dir = os.path.dirname(common.join_without_slash(dst))
    append_command(commands, 'sh', shell = 'mkdir -p %s && cp -LRf %s %s' % (sub_dir, src, sub_dir))

###############################################################################

def generate_env_file(tmp_dir, env, docker_cmd = False):
    while True:
        file = os.path.join(tmp_dir, 'env.txt.%d' % random.randint(0, 999999))
        if not os.path.isfile(file):
            break
    with open(file, 'w') as f:
        for key, value in env.items():
            value = common.eval_str_in_env(value)
            if docker_cmd:
                f.write('ENV %s "%s"\n' % (key, value))
            else:
                f.write('%s=%s\n' % (key, value))
    return file

def generate_dockerfile(commands, tmp_dir, env):
    file = generate_env_file(tmp_dir, env, True)
    append_command(commands, 'sh', shell = 'dmake_replace_vars_from_file ENV_VARS %s %s %s' % (
        file,
        os.path.join(tmp_dir, 'Dockerfile_template'),
        os.path.join(tmp_dir, 'Dockerfile')))

# ###############################################################################

class EnvBranchSerializer(YAML2PipelineSerializer):
    source    = FieldSerializer('string', optional = True, help_text = 'Source a bash file which defines the environment variables before evaluating the strings of environment variables passed in the *variables* field. It might contain environment variables itself.')
    variables = FieldSerializer('dict', child = "string", default = {}, help_text = "Defines environment variables used for the services declared in this file. You might use pre-defined environment variables (or variables sourced from the file defined in the *source* field).", example = {'ENV_TYPE': 'dev'})

    def get_replaced_variables(self, additional_variables = {}):
        env = {}
        if self.has_value() and (len(self.variables) or len(additional_variables)):
            # HACK
            # If the first varaible is empty, if is stripped out
            # So we make sure the first line is non-empty
            delimitor = 'echo "-"'
            cmd = []

            if self.source is not None:
                cmd.append('source %s' % self.source)

            variables = copy.deepcopy(self.variables)
            for k, v in additional_variables.items():
                 variables[k] = v

            cmd.append(delimitor)
            for value in variables.values():
                cmd.append('echo %s' % common.wrap_cmd(value))
            cmd.append(delimitor)

            if len(cmd) > 0:
                cmd = ' && '.join(cmd)
                output = common.run_shell_command(cmd)
                output = output.split('\n')[1:-1]
                assert(len(output) == len(variables))
                for var, value in zip(variables.keys(), output):
                    env[var] = value.strip()

        return env

class EnvSerializer(YAML2PipelineSerializer):
    default  = EnvBranchSerializer(optional = True, help_text = "List of environment variables that will be set by default.")
    branches = FieldSerializer('dict', child = EnvBranchSerializer(), default = {}, help_text = "If the branch matches one of the following fields, those variables will be defined as well, eventually replacing the default.", example = {'master': {'ENV_TYPE': 'prod'}})

class DockerBaseSerializer(YAML2PipelineSerializer):
    name                 = FieldSerializer("string", optional = True, help_text = "Base image name. If no docker user is indicated, the image will be kept locally") # Deprecated
    version              = FieldSerializer("string", optional = True, help_text = "Base image version. The branch name will be prefixed to form the docker image tag.", example = "v2") # Deprecated
    install_scripts      = FieldSerializer("array", default = [], child = FieldSerializer("path", executable = True, child_path_only = True), example = ["some/relative/script/to/run"])
    python_requirements  = FieldSerializer("path", default = "", child_path_only = True, help_text = "Path to python requirements.txt.", example = "")
    python3_requirements = FieldSerializer("path", default = "", child_path_only = True, help_text = "Path to python requirements.txt.", example = "requirements.txt")
    copy_files           = FieldSerializer("array", child = FieldSerializer("path", child_path_only = True), default = [], help_text = "Files to copy. Will be copied before scripts are ran. Paths need to be sub-paths to the build file to preserve MD5 sum-checking (which is used to decide if we need to re-build docker base image). A file 'foo/bar' will be copied in '/base/user/foo/bar'.", example = ["some/relative/file/to/copy"])

class DockerRootImageSerializer(YAML2PipelineSerializer):
    name = FieldSerializer("string", help_text = "Root image name.", example = "library/ubuntu")
    tag  = FieldSerializer("string", help_text = "Root image tag (you can use environment variables).")

    def full_name(self):
        full = self.name + ":" + self.tag
        return common.eval_str_in_env(full)

class DockerSerializer(YAML2PipelineSerializer):
    root_image   = FieldSerializer([DockerRootImageSerializer(), FieldSerializer("path", help_text = "to another dmake file, in which base the root_image will be this file's base_image.")], help_text = "The source image name to build on.", example = "ubuntu:16.04")
    base_image   = DockerBaseSerializer(optional = True, help_text = "Base (intermediate) image to speed-up builds.")
    command      = FieldSerializer("string", default = "bash", help_text = "Only used when running 'dmake shell': set the command of the container")

    def _get_tag_(self):
        if common.is_pr:
            prefix = 'pr-%s' % common.pr_id
        else:
            prefix = common.branch
        return 'base-' + prefix + '-' + self.base_image.version

    def get_docker_base_image_name_tag(self):
        if self.base_image.has_value():
            image = self.base_image.name + ":" + self._get_tag_()
            return image
        return self.root_image

class HTMLReportSerializer(YAML2PipelineSerializer):
    directory  = FieldSerializer("string", example = "reports", help_text = "Directory of the html pages.")
    index      = FieldSerializer("string", default = "index.html", help_text = "Main page.")
    title      = FieldSerializer("string", default = "HTML Report", help_text = "Main page title.")

class DockerLinkSerializer(YAML2PipelineSerializer):
    image_name       = FieldSerializer("string", example = "mongo:3.2", help_text = "Name and tag of the image to launch.")
    link_name        = FieldSerializer("string", example = "mongo", help_text = "Link name.")
    deployed_options = FieldSerializer("string", default = "", example = "-v /mnt:/data", help_text = "Additional Docker options when deployed.")
    testing_options  = FieldSerializer("string", default = "", example = "-v /mnt:/data", help_text = "Additional Docker options when testing on Jenkins.")
    probe_ports      = FieldSerializer(["string", "array"], default = "auto", child = "string", help_text = "Either 'none', 'auto' or a list of ports in the form 1234/tcp or 1234/udp")

    def probe_ports_list(self):
        if isinstance(self.probe_ports, list):
            good = True
            for p in self.probe_ports:
                i = p.find('/')
                port = p[:i]
                proto = p[(i + 1):]
                if proto not in ['udp', 'tcp']:
                    good = False
                    break
                if proto == 'udp':
                    raise DMakeException("TODO: udp support in dmake_wait_for_it")
                try:
                    if int(port) < 0:
                        good = False
                        break
                except:
                    good = False
                    break

            if good:
                return ','.join(self.probe_ports)
        elif self.probe_ports in ['auto', 'none']:
            return self.probe_ports

        raise DMakeException("Badly formatted probe ports.")

class AWSBeanStalkDeploySerializer(YAML2PipelineSerializer):
    name_prefix  = FieldSerializer("string", default = "${DMAKE_DEPLOY_PREFIX}", help_text = "The prefix to add to the 'deploy_name'. Can be useful as application name have to be unique across all users of Elastic BeanStalk.")
    region       = FieldSerializer("string", default = "eu-west-1", help_text = "The AWS region where to deploy.")
    stack        = FieldSerializer("string", default = "64bit Amazon Linux 2016.03 v2.1.6 running Docker 1.11.2")
    options      = FieldSerializer("path", example = "path/to/options.txt", help_text = "AWS Option file as described here: http://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html")
    credentials  = FieldSerializer("string", optional = True, help_text = "S3 path to the credential file to authenticate a private docker repository.")
    ebextensions = FieldSerializer("dir", optional = True, help_text = "Path to the ebextension directory. See http://docs.aws.amazon.com/elasticbeanstalk/latest/dg/ebextensions.html")

    def _serialize_(self, commands, app_name, docker_links, config, image_name, env):
        if not self.has_value():
            return

        tmp_dir = common.run_shell_command('dmake_make_tmp_dir')

        for port in config.ports:
            if port.container_port != port.host_port:
                raise DMakeException("AWS Elastic Beanstalk only supports ports binding which are the same in the container and the host.")
        ports = [{"ContainerPort": ports.container_port} for ports in config.ports]
        volumes = [
            {
                "HostDirectory": volume.host_volume,
                "ContainerDirectory": volume.container_volume
            } for volume in config.volumes if volume.host_volume != "/var/log/deepomatic" # Cannot specify a volume both in logging and mounting
        ]

        if config.pre_deploy_script  != "" or \
           config.mid_deploy_script  != "" or \
           config.post_deploy_script != "":
            raise DMakeException("Pre/Mid/Post-Deploy scripts for AWS is not supported yet.")
        if config.readiness_probe.get_cmd() != "":
            raise DMakeException("Readiness probe for AWS is not supported yet.")
        if len(config.docker_opts) > 0:
            raise DMakeException("Docker options for AWS is not supported yet.")

        # Default Dockerrun.aws.json
        data = {
            "AWSEBDockerrunVersion": "1",
            "Image": {
                "Name": image_name,
                "Update": "true"
            },
            "Ports": ports,
            "Volumes": volumes,
            "Logging": "/var/log/deepomatic"
        }

        # Generate Dockerrun.aws.json
        if self.credentials is not None:
            if self.credentials.startswith('s3://'):
                credentials = self.credentials[len('s3://'):]
            else:
                raise DMakeException("Credentials should start with 's3://'")

            credentials = credentials.split('/')
            key = '/'.join(credentials[1:])
            bucket = credentials[0]

            data["Authentication"] = {
                "Bucket": bucket,
                "Key": key
            }

        with open(os.path.join(tmp_dir, "Dockerrun.aws.json"), 'w') as dockerrun:
            json.dump(data, dockerrun)

        for var, value in env.items():
            os.environ[var] = common.eval_str_in_env(value)
        option_file = os.path.join(tmp_dir, 'options.txt')
        common.run_shell_command('dmake_replace_vars %s %s' % (self.options, option_file))
        with open(option_file, 'r') as f:
            options = json.load(f)
        for var, value in env.items():
            found = False
            for opt in options:
                if opt['OptionName'] == var:
                    found = True
                    break
            if not found:
                options.append({
                    "Namespace": "aws:elasticbeanstalk:application:environment",
                    "OptionName": var,
                    "Value": value
                })
        with open(option_file, 'w') as f:
            json.dump(options, f)

        if self.ebextensions is not None:
            common.run_shell_command('cp -LR %s %s' % (self.ebextensions, os.path.join(tmp_dir, ".ebextensions")))

        app_name = common.eval_str_in_env(self.name_prefix) + app_name
        append_command(commands, 'sh', shell = 'dmake_deploy_aws_eb "%s" "%s" "%s" "%s"' % (
            tmp_dir,
            app_name,
            self.region,
            self.stack))

class SSHDeploySerializer(YAML2PipelineSerializer):
    user = FieldSerializer("string", example = "ubuntu", help_text = "User name")
    host = FieldSerializer("string", example = "192.168.0.1", help_text = "Host address")
    port = FieldSerializer("int", default = "22", help_text = "SSH port")

    def _serialize_(self, commands, app_name, docker_links, config, image_name, env):
        if not self.has_value():
            return

        tmp_dir = common.run_shell_command('dmake_make_tmp_dir')
        app_name = app_name + "-%s" % common.branch.lower()
        env_file = generate_env_file(tmp_dir, env)

        opts = config.full_docker_opts(False) + " --env-file " + os.path.basename(env_file)

        launch_links = ""
        for link in docker_links:
            launch_links += 'if [ \\`docker ps -f name=%s | wc -l\\` = "1" ]; then set +e; docker rm -f %s 2> /dev/null ; set -e; docker run -d --name %s %s -i %s; fi\n' % (link.link_name, link.link_name, link.link_name, link.deployed_options, link.image_name)
            opts += " --link %s" % link.link_name

        # TODO: find a proper way to login on docker when deploying via SSH
        common.run_shell_command('cp -R ${HOME}/.docker* %s/ || :' % tmp_dir)

        start_file = os.path.join(tmp_dir, "start_app.sh")
        cmd = ('export IMAGE_NAME="%s" && ' % image_name) + \
              ('export APP_NAME="%s" && ' % app_name) + \
              ('export DOCKER_OPTS="%s" && ' % opts) + \
              ('export LAUNCH_LINK="%s" && ' % launch_links) + \
              ('export PRE_DEPLOY_HOOKS="%s" && ' % config.pre_deploy_script) + \
              ('export MID_DEPLOY_HOOKS="%s" && ' % config.mid_deploy_script) + \
              ('export POST_DEPLOY_HOOKS="%s" && ' % config.post_deploy_script) + \
              ('export READYNESS_PROBE=%s && ' % common.wrap_cmd(config.readiness_probe.get_cmd())) + \
               'dmake_copy_template deploy/deploy_ssh/start_app.sh %s' % start_file
        print cmd
        common.run_shell_command(cmd)

        cmd = 'dmake_deploy_ssh "%s" "%s" "%s" "%s" "%s"' % (tmp_dir, app_name, self.user, self.host, self.port)
        append_command(commands, 'sh', shell = cmd)

class K8SCDDeploySerializer(YAML2PipelineSerializer):
    context   = FieldSerializer("string", help_text = "kubectl context to use.")
    namespace = FieldSerializer("string", default = "default", help_text = "Kubernetes namespace to target")
    selectors = FieldSerializer("dict", default = {}, child = "string", help_text = "Selectors to restrict the deployment.")

    def _serialize_(self, commands, app_name, image_name, env):
        if not self.has_value():
            return

        for var, value in env.items():
            os.environ[var] = common.eval_str_in_env(value)

        selectors = []
        for key, value in self.selectors.items():
            if value.find(','):
                raise DMakeException("Cannot have ',' in selector value")
            selectors.append("%s=%s" % (key, value))
        selectors = ",".join(selectors)

        cmd = 'dmake_deploy_k8s_cd "%s" "%s" "%s" "%s" "%s" "%s"' % (common.tmp_dir, common.eval_str_in_env(self.context), common.eval_str_in_env(self.namespace), app_name, image_name, selectors)
        append_command(commands, 'sh', shell = cmd)


class DeployConfigPortsSerializer(YAML2PipelineSerializer):
    container_port    = FieldSerializer("int", example = 8000, help_text = "Port on the container")
    host_port         = FieldSerializer("int", example = 80, help_text = "Port on the host")

class DeployConfigVolumesSerializer(YAML2PipelineSerializer):
    container_volume  = FieldSerializer("string", example = "/mnt", help_text = "Path of the volume mounted in the container")
    host_volume       = FieldSerializer("string", example = "/mnt", help_text = "Path of the volume from the host")

class DeployStageSerializer(YAML2PipelineSerializer):
    description   = FieldSerializer("string", example = "Deployment on AWS and via SSH", help_text = "Deploy stage description.")
    branches      = FieldSerializer(["string", "array"], child = "string", default = ['stag'], post_validation = lambda x: [x] if common.is_string(x) else x, help_text = "Branch list for which this stag is active, '*' can be used to match any branch. Can also be a simple string.")
    env           = FieldSerializer("dict", child = "string", default = {}, example = {'AWS_ACCESS_KEY_ID': '1234', 'AWS_SECRET_ACCESS_KEY': 'abcd'}, help_text = "Additionnal environment variables for deployment.")
    aws_beanstalk = AWSBeanStalkDeploySerializer(optional = True, help_text = "Deploy via Elastic Beanstalk")
    ssh           = SSHDeploySerializer(optional = True, help_text = "Deploy via SSH")
    k8s_continuous_deployment = K8SCDDeploySerializer(optional = True, help_text = "Continuous deployment via Kubernetes. Look for all the deployments running this service.")

class ServiceDockerSerializer(YAML2PipelineSerializer):
    name             = FieldSerializer("string", optional = True, help_text = "Name of the docker image to build. By default it will be {:app_name}-{:service_name}. If there is no docker user, it won be pushed to the registry. You can use environment variables.")
    check_private    = FieldSerializer("bool",   default = True,  help_text = "Check that the docker repository is private before pushing the image.")
    tag              = FieldSerializer("string", optional = True, help_text = "Tag of the docker image to build. By default it will be {:branch_name}-{:build_id}")
    workdir          = FieldSerializer("dir",    optional = True, help_text = "Working directory of the produced docker file, must be an existing directory. By default it will be directory of the dmake file.")
    #install_targets = FieldSerializer("array", child = FieldSerializer([InstallExeSerializer(), InstallLibSerializer(), InstallDirSerializer()]), default = [], help_text = "Target files or directories to install.")
    copy_directories = FieldSerializer("array", child = "dir", default = [], help_text = "Directories to copy in the docker image.")
    install_script   = FieldSerializer("path", child_path_only = True, executable = True, optional = True, example = "install.sh", help_text = "The install script (will be run in the docker). It has to be executable.")
    entrypoint       = FieldSerializer("path", child_path_only = True, executable = True, optional = True, help_text = "Set the entrypoint of the docker image generated to run the app.")
    start_script     = FieldSerializer("path", child_path_only = True, executable = True, optional = True, example = "start.sh", help_text = "The start script (will be run in the docker). It has to be executable.")

    def get_image_name(self, service_name, latest = False):
        if self.name is None:
            name = service_name.replace('/', '-')
        else:
            name = common.eval_str_in_env(self.name)
        if self.tag is None:
            tag = common.branch.lower()
            if latest:
                tag += "-latest"
            else:
                if common.build_id is not None:
                    tag += "-%s" % common.build_id
        else:
            tag = self.tag
        image_name = name + ":" + tag
        return image_name

    def generate_build_docker(self, commands, path_dir, service_name, docker_base, env, build, config):
        if common.command == "deploy" and self.name is None:
            raise DMakeException('You need to specify an image name for %s in order to deploy the service.' % service_name)

        tmp_dir = common.run_shell_command('dmake_make_tmp_dir')
        common.run_shell_command('mkdir %s' % os.path.join(tmp_dir, 'app'))

        generate_copy_command(commands, tmp_dir, path_dir)
        for d in self.copy_directories:
            if d == path_dir:
                continue
            generate_copy_command(commands, tmp_dir, d)

        dockerfile_template = os.path.join(tmp_dir, 'Dockerfile_template')
        with open(dockerfile_template, 'w') as f:
            f.write('FROM %s\n' % docker_base)
            f.write('${ENV_VARS}\n')
            f.write("ADD app /app\n")

            if self.workdir is not None:
                workdir = self.workdir
            else:
                workdir = path_dir
            workdir = '/app/' + workdir
            f.write('WORKDIR %s\n' % workdir)

            for port in config.ports:
                f.write('EXPOSE %s\n' % port.container_port)

            if build.has_value():
                cmds = []
                for cmd in build.commands:
                    cmds += cmd
                if len(cmds) > 0:
                    cmd = ' && '.join(cmds)
                    f.write('RUN cd %s && %s\n' % (workdir, cmd))

            if self.install_script is not None:
                f.write('RUN cd %s && /app/%s\n' % (workdir, os.path.join(path_dir, self.install_script)))

            if self.start_script is not None:
                f.write('CMD ["/app/%s"]\n' % os.path.join(path_dir, self.start_script))

            if self.entrypoint is not None:
                f.write('ENTRYPOINT ["/app/%s"]\n' % os.path.join(path_dir, self.entrypoint))

        generate_dockerfile(commands, tmp_dir, env.get_replaced_variables(build.env.production if build.env.has_value() else {}))

        image_name = self.get_image_name(service_name)
        append_command(commands, 'sh', shell = 'dmake_build_docker "%s" "%s"' % (tmp_dir, image_name))

        return tmp_dir

class ReadinessProbeSerializer(YAML2PipelineSerializer):
    command               = FieldSerializer("array", child = "string", default = [], example = ['cat', '/tmp/worker_ready'], help_text = "The command to run to check if the container is ready. The command should fail with a non-zero code if not ready.")
    initial_delay_seconds = FieldSerializer("int", default = 5, example = "5", help_text = "The delay before the first probe is launched")
    period_seconds        = FieldSerializer("int", default = 5, example = "5", help_text = "The delay between two first probes")
    max_seconds           = FieldSerializer("int", default = 0, example = "40", help_text = "The maximum delay after failure")

    def get_cmd(self):
        if not self.has_value() or len(self.command) == 0:
            return ""

        if self.max_seconds > 0:
            condition = "$T -le %s" % self.max_seconds
        else:
            condition = "1"

        period = max(int(self.period_seconds), 1)

        # Make the command with "" around parameters
        cmd = self.command[0] + ' ' + (' '.join([common.wrap_cmd(c) for c in self.command[1:]]))
        cmd = "T=0; sleep %s; while [ %s ]; do %s; if [ '$?' == '0' ]; then exit 0; fi; T=$((T+%d)); sleep %d; done; exit 1;" % (self.initial_delay_seconds, condition, cmd, period, period)
        return 'bash -c %s' % common.wrap_cmd(cmd).replace('$', '\$')

class DeployConfigSerializer(YAML2PipelineSerializer):
    docker_image       = ServiceDockerSerializer(optional = True, help_text = "Docker to build for running and deploying.")
    docker_links_names = FieldSerializer("array", child = "string", default = [], example = ['mongo'], help_text = "The docker links names to bind to for this test. Must be declared at the root level of some dmake file of the app.")
    docker_opts        = FieldSerializer("string", default = "", example = "--privileged", help_text = "Docker options to add.")
    ports              = FieldSerializer("array", child = DeployConfigPortsSerializer(), default = [], help_text = "Ports to open.")
    volumes            = FieldSerializer("array", child = DeployConfigVolumesSerializer(), default = [], help_text = "Volumes to open.")
    readiness_probe    = ReadinessProbeSerializer(optional = True, help_text = "A probe that waits until the container is ready.")

    # Deprecated
    pre_deploy_script  = FieldSerializer("string", default = "", child_path_only = True, example = "my/pre_deploy/script", help_text = "Scripts to run before launching new version.")
    mid_deploy_script  = FieldSerializer("string", default = "", child_path_only = True, example = "my/mid_deploy/script", help_text = "Scripts to run after launching new version and before stopping the old one.")
    post_deploy_script = FieldSerializer("string", default = "", child_path_only = True, example = "my/post_deploy/script", help_text = "Scripts to run after stopping old version.")

    def full_docker_opts(self, testing_mode):
        if not self.has_value():
            return ""

        opts = []
        for ports in self.ports:
            if testing_mode:
                opts.append("-p %s" % ports.container_port)
            else:
                opts.append("-p 0.0.0.0:%s:%s" % (ports.host_port, ports.container_port))

        for volumes in self.volumes:
            if testing_mode:
                host_volume = os.path.join(common.cache_dir, 'volumes', volumes.host_volume)
                try:
                    os.mkdir(host_volume)
                except OSError:
                    pass
            else:
                host_volume = volumes.host_volume

            # On MacOs, the /var directory is actually in /private
            # So you have to activate /private/var in the shard directories
            if common.uname == "Darwin" and host_volume.startswith('/var/'):
                host_volume = '/private/' + host_volume

            opts.append("-v %s:%s" % (common.join_without_slash(host_volume), common.join_without_slash(volumes.container_volume)))

        docker_opts = self.docker_opts
        if testing_mode:
            docker_opts = docker_opts.replace('--privileged', '')
        opts = docker_opts + " " + (" ".join(opts))
        return opts

class DeploySerializer(YAML2PipelineSerializer):
    deploy_name = FieldSerializer("string", optional = True, example = "", help_text = "The name used for deployment. Will default to 'app_name-service_name' if not specified")
    stages      = FieldSerializer("array", child = DeployStageSerializer(), help_text = "Deployment possibilities")

    def generate_build_docker(self, commands, path_dir, service_name, docker_base, env, build, config):
        if config.docker_image.has_value():
            config.docker_image.generate_build_docker(commands, path_dir, service_name, docker_base, env, build, config)

    def generate_deploy(self, commands, app_name, service_name, package_dir, docker_links, env, config):
        if self.deploy_name is not None:
            app_name = self.deploy_name
        else:
            app_name = "%s-%s" % (app_name, service_name)
        app_name = common.eval_str_in_env(app_name)

        links = []
        for link_name in config.docker_links_names:
            if link_name not in docker_links:
                raise DMakeException("Unknown link name: '%s'" % link_name)
            links.append(docker_links[link_name])

        image_name = config.docker_image.get_image_name(service_name)
        append_command(commands, 'sh', shell = 'dmake_push_docker_image "%s" "%s"' % (image_name, "1" if config.docker_image.check_private else "0"))
        image_latest = config.docker_image.get_image_name(service_name, latest = True)
        append_command(commands, 'sh', shell = 'docker tag %s %s && dmake_push_docker_image "%s" "%s"' % (image_name, image_latest, image_latest, "1" if config.docker_image.check_private else "0"))

        for stage in self.stages:
            branches = stage.branches
            if common.branch not in branches and '*' not in branches:
                continue

            branch_env = env.get_replaced_variables(stage.env)
            stage.aws_beanstalk._serialize_(commands, app_name, links, config, image_name, branch_env)
            stage.ssh._serialize_(commands, app_name, links, config, image_name, branch_env)
            stage.k8s_continuous_deployment._serialize_(commands, app_name, image_name, branch_env)

class DataVolumeSerializer(YAML2PipelineSerializer):
    container_volume  = FieldSerializer("string", example = "/mnt", help_text = "Path of the volume mounted in the container")
    source            = FieldSerializer("string", example = "s3://my-bucket/some/folder", help_text = "Remote bucket to mount. Only s3 is supported for now and the path must start with 's3://'")

    def get_mount_opt(self):
        scheme = None
        path = ""
        i = self.source.find('://')
        if i >= 0:
            scheme = self.source[:i]
            path = self.source[(i + 3):]

        if scheme == "s3":
            path = os.path.join(common.config_dir, 'data_volumes', 's3', path)
            common.run_shell_command('aws s3 sync %s %s' % (self.source, path))
        else:
            raise DMakeException("Field source is expected to start with 's3://'")

        return '-v %s:%s' % (path, self.container_volume)

class TestSerializer(YAML2PipelineSerializer):
    docker_links_names = FieldSerializer("array", child = "string", default = [], example = ['mongo'], help_text = "The docker links names to bind to for this test. Must be declared at the root level of some dmake file of the app.")
    data_volumes       = FieldSerializer("array", child = DataVolumeSerializer(), default = [], help_text = "The read only data volumes to mount. Only S3 is supported for now.")
    commands           = FieldSerializer("array", child = "string", example = ["python manage.py test"], help_text = "The commands to run for integration tests.")
    junit_report       = FieldSerializer("string", optional = True, example = "test-reports/*.xml", help_text = "Uses JUnit plugin to generate unit test report.")
    cobertura_report   = FieldSerializer("string", optional = True, example = "", help_text = "Publish a Cobertura report (not working for now).")
    html_report        = HTMLReportSerializer(optional = True, help_text = "Publish an HTML report.")

    def generate_test(self, commands, app_name, docker_cmd, docker_links):
        if not self.has_value():
            return

        for cmd in self.commands:
            append_command(commands, 'sh', shell = docker_cmd + cmd)

        if self.junit_report is not None:
            append_command(commands, 'junit', report = self.junit_report)

        if self.cobertura_report is not None:
            append_command(commands, 'cobertura', report = self.cobertura_report)

        html = self.html_report._value_()
        if html is not None:
            append_command(commands, 'publishHTML',
                directory = html['directory'],
                index     = html['index'],
                title     = html['title'])

class ServiceSerializer(YAML2PipelineSerializer):
    service_name    = FieldSerializer("string", default = "", help_text = "The name of the application part.", example = "api", no_slash_no_space = True)
    needed_services = FieldSerializer("array", child = FieldSerializer("string", blank = False), default = [], help_text = "List here the sub apps (as defined by service_name) of our application that are needed for this sub app to run.", example = ["worker"])
    sources         = FieldSerializer("array", child = FieldSerializer(["path", "dir"]), optional = True, help_text = "If specified, this service will be considered as updated only when the content of those directories or files have changed.", example = 'path/to/app')
    config          = DeployConfigSerializer(optional = True, help_text = "Deployment configuration.")
    tests           = TestSerializer(optional = True, help_text = "Unit tests list.")
    deploy          = DeploySerializer(optional = True, help_text = "Deploy stage")

class BuildEnvSerializer(YAML2PipelineSerializer):
    testing    = FieldSerializer("dict", child = "string", default = {}, help_text = "List of environment variables that will be set when building for testing.", example = {'MY_ENV_VARIABLE': '1', 'ENV_TYPE': 'dev'})
    production = FieldSerializer("dict", child = "string", default = {}, help_text = "List of environment variables that will be set when building for production.", example = {'MY_ENV_VARIABLE': '1', 'ENV_TYPE': 'prod'})

class BuildSerializer(YAML2PipelineSerializer):
    env      = BuildEnvSerializer(optional = True, help_text = "Environment variable to define when building.")
    commands = FieldSerializer("array", default = [], child = FieldSerializer(["string", "array"], child = "string", post_validation = lambda x: [x] if common.is_string(x) else x), help_text ="Command list (or list of lists, in which case each list of commands will be executed in paralell) to build.", example = ["cmake .", "make"])

class DMakeFileSerializer(YAML2PipelineSerializer):
    dmake_version      = FieldSerializer("string", help_text = "The dmake version.", example = "0.1")
    app_name           = FieldSerializer("string", help_text = "The application name.", example = "my_app", no_slash_no_space = True)
    blacklist          = FieldSerializer("array", child = "path", default = [], help_text = "List of dmake files to blacklist.", child_path_only = True, example = ['some/sub/dmake.yml'])
    env                = FieldSerializer(["path", EnvSerializer()], optional = True, help_text = "Environment variables to embed in built docker images.")
    docker             = FieldSerializer([DockerSerializer(), FieldSerializer("path", help_text = "to another dmake file (which will be added to dependencies) that declares a docker field, in which case it replaces this file's docker field.")], help_text = "The environment in which to build and deploy.")
    docker_links       = FieldSerializer("array", child = DockerLinkSerializer(), default = [], help_text = "List of link to create, they are shared across the whole application, so potentially across multiple dmake files.")
    build              = BuildSerializer(optional = True, help_text = "Commands to run for building the application.")
    pre_test_commands  = FieldSerializer("array", default = [], child = "string", help_text = "Command list to run before running tests.")
    post_test_commands = FieldSerializer("array", default = [], child = "string", help_text = "Command list to run after running tests.")
    services           = FieldSerializer("array", child = ServiceSerializer(), default = [], help_text = "Service list.")