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
               description: 'Application to test. You can also specify a service name if there is no ambiguity. Use * to force the test of all applications.')
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
    env.PATH = "${env.WORKSPACE}/deepomatic/dmake:${env.WORKSPACE}/deepomatic/dmake/utils:${env.PATH}"

    // Setup environment variables as Jenkins would do
    env.REPO=params.REPO_TO_TEST
    env.BRANCH_NAME=params.BRANCH_TO_TEST
    if (params.REPO_TO_TEST != 'deepomatic/dmake') {
        env.BUILD_ID = 0
    }
    env.CHANGE_BRANCH=""
    env.CHANGE_TARGET=""
    env.CHANGE_ID=""
    env.DMAKE_PAUSE_ON_ERROR_BEFORE_CLEANUP=1
    env.DMAKE_DEBUG=1
  }

  def python_versions = ['2', '3']
  def builders = [:]
  for (x in python_versions) {
    def version = x // Need to bind the label variable before the closure, otherwise the last value is applied to all closures
    builders["python-${version}"] = {
      stage("Python ${version}.x") {
        // Clone repo to test
        sh ("echo 'Cloning ${params.BRANCH_TO_TEST} from https://github.com/${params.REPO_TO_TEST}.git'")
        checkout changelog: false,
        poll: false,
        scm: [$class: 'GitSCM', branches: [[name: params.BRANCH_TO_TEST]], doGenerateSubmoduleConfigurations: false,
              extensions: [[$class: 'WipeWorkspace'],
                           [$class: 'RelativeTargetDirectory', relativeTargetDir: "workspace-python-${version}"],
                           [$class: 'SubmoduleOption', disableSubmodules: false, parentCredentials: false, recursiveSubmodules: true, reference: '', trackingSubmodules: false],
                           [$class: 'LocalBranch', localBranch: params.BRANCH_TO_TEST]],
              submoduleCfg: [], userRemoteConfigs: [[credentialsId: 'dmake-http', url: "https://github.com/${params.REPO_TO_TEST}.git"]]]

        dir("workspace-python-${version}") {
          sh "virtualenv -p python${version} .venv"
          sh ". .venv/bin/activate && pip install -r requirements.txt"
          sh ". .venv/bin/activate && dmake test -d '${params.DMAKE_APP_TO_TEST}'"
          sshagent (credentials: (env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS ?
                                  env.DMAKE_JENKINS_SSH_AGENT_CREDENTIALS : '').tokenize(',')) {
            load 'DMakefile'
          }
        }
      }
    }
  }

  parallel builders
}
