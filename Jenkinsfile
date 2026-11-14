// Declarative Jenkins Pipeline for the AegisPay Multi-Layer QA Automation Suite.
// Orchestrates Python static analysis, FastAPI/Hypothesis/Jira API tests, dual-engine
// Web E2E (Playwright + Selenium WebDriver), Android Appium/ADB (Python + Kotlin/Gradle),
// Unreal Engine Gauntlet/log regression checks, and post-build HTML + Jira reporting.

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '15'))
        disableConcurrentBuilds()
    }

    environment {
        QA_MOBILE_MODE   = 'mock'
        PYTHONUNBUFFERED = '1'
        JIRA_BASE_URL    = credentials('jira-base-url-optional')
        JIRA_USER_EMAIL  = credentials('jira-user-email-optional')
        JIRA_API_TOKEN   = credentials('jira-api-token-optional')
        JIRA_PROJECT_KEY = 'QA'
    }

    stages {
        stage('1. Environment & Toolchain Bootstrap') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    python -m pip install --upgrade pip
                    pip install -e ".[dev]"
                    python -m playwright install chromium
                '''
            }
        }

        stage('2. Static Analysis (Ruff + Mypy Strict)') {
            steps {
                sh '''
                    . .venv/bin/activate
                    ruff check .
                    ruff format --check .
                    mypy sut qa_framework tests scripts
                '''
            }
        }

        stage('3. Layer 1: API, Hypothesis Fuzzing & Jira Client') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pytest tests/api -v --junitxml=reports/junit-api.xml
                '''
            }
        }

        stage('4. Layer 2: Dual-Engine Web E2E (Playwright + Selenium)') {
            parallel {
                stage('Playwright Chromium E2E') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            pytest tests/web/test_portal_e2e.py -v --junitxml=reports/junit-playwright.xml
                        '''
                    }
                }
                stage('Selenium WebDriver E2E') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            pytest tests/web/test_selenium_e2e.py -v --junitxml=reports/junit-selenium.xml
                        '''
                    }
                }
            }
        }

        stage('5. Layer 3: Mobile QA (Appium/ADB + Kotlin/JUnit5)') {
            parallel {
                stage('Python Appium POM & ADB Harness') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            pytest tests/mobile -v --junitxml=reports/junit-mobile.xml
                        '''
                    }
                }
                stage('Kotlin Appium Java-Client + JUnit5') {
                    steps {
                        dir('mobile-kotlin') {
                            sh 'chmod +x gradlew && ./gradlew test --no-daemon'
                        }
                    }
                }
            }
        }

        stage('6. Layer 4: Unreal Engine Gauntlet & Frame-Budget QA') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pytest tests/unreal -v --junitxml=reports/junit-unreal.xml
                '''
            }
        }

        stage('7. Unified Report Generation & Visual Telemetry') {
            steps {
                sh '''
                    . .venv/bin/activate
                    python scripts/generate_reports.py
                '''
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/junit-*.xml, mobile-kotlin/build/test-results/test/*.xml'
            archiveArtifacts artifacts: 'reports/qa-summary.json, reports/qa-report.html, docs/images/*.png', allowEmptyArchive: true
            publishHTML(target: [
                allowMissing: true,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: 'reports',
                reportFiles: 'qa-report.html',
                reportName: 'AegisPay 4-Layer QA Report'
            ])
        }
        failure {
            sh '''
                . .venv/bin/activate
                python -c "
                import json, pathlib
                from qa_framework.integrations.jira_reporter import build_defects_from_summary, export_dry_run_defects
                summary_path = pathlib.Path('reports/qa-summary.json')
                if summary_path.exists():
                    summary = json.loads(summary_path.read_text())
                    defects = build_defects_from_summary(summary, project_key='QA', build_url='${BUILD_URL}')
                    export_dry_run_defects(defects, pathlib.Path('reports/jira-defects-dry-run.json'))
                "
            '''
            archiveArtifacts artifacts: 'reports/jira-defects-dry-run.json', allowEmptyArchive: true
        }
    }
}
