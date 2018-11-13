properties([
    parameters([
        string(name: 'REPO_TO_TEST',
               defaultValue: 'deepomatic/dmake',
               description: 'The repository to check out.'),
        string(name: 'BRANCH_TO_TEST',
               defaultValue: env.CHANGE_BRANCH ?: env.BRANCH_NAME,
               description: 'The branch to check out. Only used when testing a directory different from deepomatic/dmake.'),
        string(name: 'DMAKE_APP_TO_TEST',
               defaultValue: '*',
               description: 'Application to test. You can also specify a service name if there is no ambiguity. Use * to force the test of all applications.'),
        booleanParam(name: 'DMAKE_SKIP_TESTS',
                     defaultValue: false,
                     description: 'Skip tests if checked'),
        booleanParam(name: 'DMAKE_DEBUG',
                     defaultValue: true,
                     description: 'Enable dmake debug logs'),
        booleanParam(name: 'DMAKE_PAUSE_ON_ERROR_BEFORE_CLEANUP',
                     defaultValue: true,
                     description: 'Ask user confirmation before DMake cleanup.'),
        booleanParam(name: 'DMAKE_FORCE_BASE_IMAGE_BUILD',
                     defaultValue: false,
                     description: 'Force base image build (don\'t use base image cache)'),
        string(name: 'CUSTOM_ENVIRONMENT',
               defaultValue: '',
               description: '(optional) Custom environment variables, for custom build. Example: \'FOO=1 BAR=2\'')
    ]),
    pipelineTriggers([])
])


node {
  // This displays colors using the 'xterm' ansi color map.
  stage('Setup') {
    checkout scm
    try {
        sh 'git submodule update --init'
    } catch(error) {
        deleteDir()
        checkout scm
        sh 'git submodule update --init'
    }

    // Use this version of dmake
    env.PYTHONPATH = "${env.WORKSPACE}:${env.PYTHONPATH}"
    env.PATH = "${env.WORKSPACE}/dmake:${env.WORKSPACE}/dmake/utils:${env.PATH}"

    // Clone repo to test
    sh ("echo 'Cloning ${params.BRANCH_TO_TEST} from https://github.com/${params.REPO_TO_TEST}.git'")
        checkout changelog: false,
                 poll: false,
                 scm: [$class: 'GitSCM', branches: [[name: params.BRANCH_TO_TEST]], doGenerateSubmoduleConfigurations: false,
                 extensions: [[$class: 'WipeWorkspace'],
                              [$class: 'RelativeTargetDirectory', relativeTargetDir: 'workspace'],
                              [$class: 'SubmoduleOption', disableSubmodules: false, parentCredentials: false, recursiveSubmodules: true, reference: '', trackingSubmodules: false],
                              [$class: 'LocalBranch', localBranch: params.BRANCH_TO_TEST]],
                 submoduleCfg: [], userRemoteConfigs: [[credentialsId: 'dmake-http', url: "https://github.com/${params.REPO_TO_TEST}.git"]]]

    // Setup environment variables as Jenkins would do
    env.REPO=params.REPO_TO_TEST
    env.BRANCH_NAME=params.BRANCH_TO_TEST
    if (params.REPO_TO_TEST != 'deepomatic/dmake') {
        env.BUILD_ID = 0
    }
    env.CHANGE_BRANCH=""
    env.CHANGE_TARGET=""
    env.CHANGE_ID=""
    // params are automatically exposed as environment variables
    // but booleans to string generates "true"
    if (params.DMAKE_DEBUG) {
        env.DMAKE_DEBUG=1
    }
    if (params.DMAKE_PAUSE_ON_ERROR_BEFORE_CLEANUP) {
        env.DMAKE_PAUSE_ON_ERROR_BEFORE_CLEANUP=1
    }
  }
  stage('Python 2.x') {
    sh "virtualenv workspace/.venv2"
    sh ". workspace/.venv2/bin/activate && pip install -r requirements.txt"
    dir('workspace') {
      sh ". .venv2/bin/activate && pytest -v --junit-xml=junit.xml --junit-prefix=python2"
      junit keepLongStdio: true, testResults: 'junit.xml'
      sh ". .venv2/bin/activate && ${params.CUSTOM_ENVIRONMENT} dmake test -d '${params.DMAKE_APP_TO_TEST}'"
      sshagent (credentials: (env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS ?
                  env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS : '').tokenize(',')) {
        load 'DMakefile'
      }
    }
  }

  stage('Python 3.x') {
    sh "virtualenv -p python3 workspace/.venv3"
    sh ". workspace/.venv3/bin/activate && pip install -r requirements.txt"
    dir('workspace') {
      sh ". .venv3/bin/activate && pytest -v --junit-xml=junit.xml --junit-prefix=python3"
      junit keepLongStdio: true, testResults: 'junit.xml'
      sh ". .venv3/bin/activate && ${params.CUSTOM_ENVIRONMENT} dmake test -d '${params.DMAKE_APP_TO_TEST}'"
      sshagent (credentials: (env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS ?
                  env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS : '').tokenize(',')) {
        load 'DMakefile'
      }
    }
  }
}
