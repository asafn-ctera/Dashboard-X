#!/bin/bash
# =============================================================================
# Jenkins CLI Helper Script
# =============================================================================
# Usage: ./jenkins.sh <command> [options]
#
# Commands:
#   jobs                    - List all jobs
#   search <pattern>        - Search jobs by name
#   status <job>            - Get job status
#   build <job> [params]    - Trigger a build
#   log <job> [build#]      - Get build console log
#   queue                   - Show build queue
#   info <job>              - Get job details
#
# =============================================================================

# Load credentials from environment or config file
JENKINS_URL="${JENKINS_URL:-https://jenkins.ctera.dev}"
JENKINS_USER="${JENKINS_USER:-}"
JENKINS_TOKEN="${JENKINS_TOKEN:-}"

# Config file location
CONFIG_FILE="${HOME}/.jenkins-config"

# Load config if exists
if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

check_credentials() {
    if [[ -z "$JENKINS_USER" || -z "$JENKINS_TOKEN" ]]; then
        echo -e "${RED}Error: Jenkins credentials not configured${NC}"
        echo ""
        echo "Please set up credentials in one of these ways:"
        echo ""
        echo "1. Create config file: $CONFIG_FILE"
        echo "   JENKINS_USER=\"your-username\""
        echo "   JENKINS_TOKEN=\"your-api-token\""
        echo ""
        echo "2. Export environment variables:"
        echo "   export JENKINS_USER=\"your-username\""
        echo "   export JENKINS_TOKEN=\"your-api-token\""
        echo ""
        echo "To get your API token:"
        echo "  1. Go to ${JENKINS_URL}/me/configure"
        echo "  2. Click 'Add new Token' under API Token"
        echo "  3. Copy the generated token"
        exit 1
    fi
}

jenkins_api() {
    local endpoint="$1"
    local method="${2:-GET}"
    local data="$3"
    
    local url="${JENKINS_URL}${endpoint}"
    
    if [[ "$method" == "POST" ]]; then
        curl -s -X POST -u "${JENKINS_USER}:${JENKINS_TOKEN}" "$url" ${data:+-d "$data"}
    else
        curl -s -u "${JENKINS_USER}:${JENKINS_TOKEN}" "$url"
    fi
}

# =============================================================================
# Commands
# =============================================================================

cmd_jobs() {
    check_credentials
    echo -e "${BLUE}Fetching jobs from Jenkins (768 total)...${NC}"
    echo ""
    
    jenkins_api "/api/json" | \
        jq -r '.jobs[] | "\(.color // "folder" | if . == "blue" then "✓" elif . == "red" then "✗" elif . == "notbuilt" then "○" elif . == "folder" then "📁" elif . == "disabled" then "⊘" elif . | contains("anime") then "⟳" else "?" end) \(.name)"' 2>/dev/null || \
        echo "Failed to fetch jobs. Check your credentials."
}

cmd_search() {
    local pattern="$1"
    if [[ -z "$pattern" ]]; then
        echo "Usage: $0 search <pattern>"
        exit 1
    fi
    
    check_credentials
    echo -e "${BLUE}Searching for jobs matching: ${pattern}${NC}"
    echo ""
    
    jenkins_api "/api/json" | \
        jq -r --arg p "$pattern" '.jobs[] | select(.name | test($p; "i")) | "\(.color // "folder" | if . == "blue" then "✓" elif . == "red" then "✗" elif . == "notbuilt" then "○" elif . == "folder" then "📁" elif . == "disabled" then "⊘" elif . | contains("anime") then "⟳" else "?" end) \(.name)"' 2>/dev/null
}

cmd_status() {
    local job="$1"
    if [[ -z "$job" ]]; then
        echo "Usage: $0 status <job-name>"
        exit 1
    fi
    
    check_credentials
    
    # URL encode the job name
    local encoded_job=$(echo "$job" | sed 's/ /%20/g' | sed 's/\//%2F/g')
    
    echo -e "${BLUE}Job: ${job}${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local result=$(jenkins_api "/job/${encoded_job}/lastBuild/api/json")
    
    if echo "$result" | jq -e . >/dev/null 2>&1; then
        local build_num=$(echo "$result" | jq -r '.number')
        local status=$(echo "$result" | jq -r '.result // "IN PROGRESS"')
        local building=$(echo "$result" | jq -r '.building')
        local duration=$(echo "$result" | jq -r '.duration')
        local timestamp=$(echo "$result" | jq -r '.timestamp')
        
        # Convert timestamp to human readable
        local date_str=$(date -r $((timestamp/1000)) "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "N/A")
        
        # Status color
        local status_color="$NC"
        if [[ "$building" == "true" ]]; then
            status_color="$YELLOW"
            status="BUILDING"
        elif [[ "$status" == "SUCCESS" ]]; then
            status_color="$GREEN"
        elif [[ "$status" == "FAILURE" ]]; then
            status_color="$RED"
        fi
        
        echo -e "Build #:    ${build_num}"
        echo -e "Status:     ${status_color}${status}${NC}"
        echo -e "Started:    ${date_str}"
        echo -e "Duration:   $((duration/1000))s"
        echo -e "URL:        ${JENKINS_URL}/job/${encoded_job}/${build_num}/"
    else
        echo -e "${RED}Failed to get job status. Job may not exist or no builds yet.${NC}"
    fi
}

cmd_build() {
    local job="$1"
    shift
    local params="$*"
    
    if [[ -z "$job" ]]; then
        echo "Usage: $0 build <job-name> [param1=value1 param2=value2 ...]"
        exit 1
    fi
    
    check_credentials
    
    local encoded_job=$(echo "$job" | sed 's/ /%20/g' | sed 's/\//%2F/g')
    
    echo -e "${YELLOW}Triggering build: ${job}${NC}"
    
    local endpoint="/job/${encoded_job}/build"
    if [[ -n "$params" ]]; then
        # Convert params to JSON
        local json_params="{"
        local first=true
        for param in $params; do
            local key="${param%%=*}"
            local value="${param#*=}"
            if [[ "$first" == "true" ]]; then
                first=false
            else
                json_params+=","
            fi
            json_params+="\"${key}\":\"${value}\""
        done
        json_params+="}"
        endpoint="/job/${encoded_job}/buildWithParameters?$(echo "$params" | sed 's/ /\&/g')"
    fi
    
    local response=$(curl -s -w "\n%{http_code}" -X POST -u "${JENKINS_USER}:${JENKINS_TOKEN}" "${JENKINS_URL}${endpoint}")
    local http_code=$(echo "$response" | tail -n1)
    
    if [[ "$http_code" == "201" || "$http_code" == "200" ]]; then
        echo -e "${GREEN}✓ Build triggered successfully!${NC}"
        echo -e "View at: ${JENKINS_URL}/job/${encoded_job}/"
    else
        echo -e "${RED}✗ Failed to trigger build (HTTP ${http_code})${NC}"
        echo "$response" | head -n -1
    fi
}

cmd_log() {
    local job="$1"
    local build="${2:-lastBuild}"
    
    if [[ -z "$job" ]]; then
        echo "Usage: $0 log <job-name> [build-number]"
        echo "       Use 'lastBuild' or a number (e.g., 42)"
        exit 1
    fi
    
    check_credentials
    
    local encoded_job=$(echo "$job" | sed 's/ /%20/g' | sed 's/\//%2F/g')
    
    echo -e "${BLUE}Fetching console log for ${job} #${build}...${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    jenkins_api "/job/${encoded_job}/${build}/consoleText"
}

cmd_queue() {
    check_credentials
    echo -e "${BLUE}Build Queue${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local result=$(jenkins_api "/queue/api/json")
    
    local count=$(echo "$result" | jq '.items | length')
    
    if [[ "$count" == "0" ]]; then
        echo "Queue is empty"
    else
        echo "$result" | jq -r '.items[] | "[\(.id)] \(.task.name) - \(.why // "Waiting")"'
    fi
}

cmd_info() {
    local job="$1"
    if [[ -z "$job" ]]; then
        echo "Usage: $0 info <job-name>"
        exit 1
    fi
    
    check_credentials
    
    local encoded_job=$(echo "$job" | sed 's/ /%20/g' | sed 's/\//%2F/g')
    
    echo -e "${BLUE}Job Information: ${job}${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local result=$(jenkins_api "/job/${encoded_job}/api/json")
    
    if echo "$result" | jq -e . >/dev/null 2>&1; then
        echo "$result" | jq -r '
            "Name:        \(.displayName // .name)",
            "URL:         \(.url)",
            "Buildable:   \(.buildable)",
            "In Queue:    \(.inQueue)",
            "Last Build:  #\(.lastBuild.number // "N/A")",
            "Last Success: #\(.lastSuccessfulBuild.number // "N/A")",
            "Last Failure: #\(.lastFailedBuild.number // "N/A")"
        '
        
        # Check for parameters
        local has_params=$(echo "$result" | jq '.property[] | select(.parameterDefinitions) | .parameterDefinitions | length')
        if [[ -n "$has_params" && "$has_params" != "0" ]]; then
            echo ""
            echo -e "${YELLOW}Parameters:${NC}"
            echo "$result" | jq -r '.property[] | select(.parameterDefinitions) | .parameterDefinitions[] | "  - \(.name): \(.description // "no description") [default: \(.defaultParameterValue.value // "none")]"'
        fi
    else
        echo -e "${RED}Failed to get job info. Job may not exist.${NC}"
    fi
}

cmd_mybuilds() {
    local job_pattern="${1:-}"
    local limit="${2:-15}"
    
    check_credentials
    
    if [[ -z "$job_pattern" ]]; then
        echo -e "${BLUE}Usage: $0 mybuilds <job-pattern> [limit]${NC}"
        echo ""
        echo "Examples:"
        echo "  $0 mybuilds portal          # Search 'portal' jobs for your builds"
        echo "  $0 mybuilds 'private_portal'   # Search specific job"
        echo "  $0 mybuilds centos 10       # Show last 10 of your builds in 'centos' jobs"
        echo ""
        echo "This searches jobs matching the pattern for builds you triggered."
        return 0
    fi
    
    echo -e "${BLUE}Searching '${job_pattern}' jobs for builds by ${JENKINS_USER}...${NC}"
    echo ""
    
    # Get matching jobs
    local jobs=$(jenkins_api "/api/json" | jq -r --arg p "$job_pattern" '.jobs[] | select(.name | test($p; "i")) | .name' 2>/dev/null)
    
    if [[ -z "$jobs" ]]; then
        echo "No jobs found matching: $job_pattern"
        return 1
    fi
    
    local tmpfile=$(mktemp)
    local job_count=$(echo "$jobs" | wc -l | tr -d ' ')
    echo -e "Found ${job_count} matching jobs, scanning recent builds..."
    echo ""
    
    echo "$jobs" | while read -r job; do
        [[ -z "$job" ]] && continue
        
        local encoded_job=$(echo "$job" | sed 's/ /%20/g' | sed 's/\//%2F/g')
        
        # Get recent build numbers for this job
        local build_nums=$(jenkins_api "/job/${encoded_job}/api/json" | jq -r '.builds[0:10]? | .[].number?' 2>/dev/null)
        
        for build_num in $build_nums; do
            [[ -z "$build_num" ]] && continue
            
            # Get build details including who triggered it
            local build_info=$(jenkins_api "/job/${encoded_job}/${build_num}/api/json" 2>/dev/null)
            
            # Extract userId from causes
            local triggered_by=$(echo "$build_info" | jq -r '[.actions[]?.causes? | select(. != null) | .[] | .userId? // .userName?] | map(select(. != null)) | .[0] // ""' 2>/dev/null)
            
            # Check if this user triggered the build (case insensitive)
            local triggered_lower=$(echo "$triggered_by" | tr '[:upper:]' '[:lower:]')
            local user_lower=$(echo "$JENKINS_USER" | tr '[:upper:]' '[:lower:]')
            if [[ "$triggered_lower" == "$user_lower" ]]; then
                local result=$(echo "$build_info" | jq -r '.result // "BUILDING"')
                local timestamp=$(echo "$build_info" | jq -r '.timestamp // 0')
                echo "${timestamp}|${build_num}|${result}|${job}" >> "$tmpfile"
            fi
        done
    done
    
    # Sort by timestamp and display
    if [[ -s "$tmpfile" ]]; then
        echo -e "${GREEN}Your builds in matching jobs:${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        printf "%-10s %-12s %-50s\n" "BUILD" "STATUS" "JOB"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        sort -t'|' -k1 -rn "$tmpfile" | head -n "$limit" | while IFS='|' read -r ts num result jobname; do
            local status_color="$NC"
            if [[ "$result" == "SUCCESS" ]]; then
                status_color="$GREEN"
            elif [[ "$result" == "FAILURE" ]]; then
                status_color="$RED"
            elif [[ "$result" == "BUILDING" || "$result" == "null" ]]; then
                status_color="$YELLOW"
                result="BUILDING"
            fi
            printf "%-10s ${status_color}%-12s${NC} %-50s\n" "#$num" "$result" "$jobname"
        done
        
        local total=$(wc -l < "$tmpfile" | tr -d ' ')
        echo ""
        echo "Found $total builds triggered by you."
    else
        echo "No builds found triggered by you in matching jobs."
    fi
    
    rm -f "$tmpfile"
}

cmd_running() {
    check_credentials
    echo -e "${BLUE}Currently running builds:${NC}"
    echo ""
    
    # Get running builds from executors
    local running=$(jenkins_api "/computer/api/json?tree=computer[displayName,executors[currentExecutable[url,fullDisplayName,timestamp,building]],oneOffExecutors[currentExecutable[url,fullDisplayName,timestamp,building]]]" | jq -r '
        .computer[] | 
        .executors[]?.currentExecutable? // empty, 
        .oneOffExecutors[]?.currentExecutable? // empty | 
        select(. != null and .building == true) |
        "⟳ \(.fullDisplayName)"
    ' 2>/dev/null)
    
    if [[ -n "$running" ]]; then
        echo "$running"
    else
        echo "No builds currently running."
    fi
    
    echo ""
    echo -e "${YELLOW}Build Queue:${NC}"
    cmd_queue
}

cmd_help() {
    echo "Jenkins CLI Helper"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  jobs                        List all jobs"
    echo "  search <pattern>            Search jobs by name (regex)"
    echo "  status <job>                Get last build status"
    echo "  build <job> [params]        Trigger a build"
    echo "  log <job> [build#]          Get console log"
    echo "  queue                       Show build queue"
    echo "  info <job>                  Get job details and parameters"
    echo "  running                     Show currently running builds"
    echo "  mybuilds <pattern> [limit]  Find YOUR builds in matching jobs"
    echo "  help                        Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 jobs"
    echo "  $0 search portal"
    echo "  $0 status my-job"
    echo "  $0 build my-job BRANCH=main ENV=staging"
    echo "  $0 log my-job 42"
    echo "  $0 running"
    echo "  $0 mybuilds portal          # Find your builds in 'portal' jobs"
    echo "  $0 mybuilds centos 20       # Find your builds in 'centos' jobs (limit 20)"
    echo ""
    echo "Configuration: $CONFIG_FILE"
    echo "Jenkins URL:   $JENKINS_URL"
}

# =============================================================================
# Main
# =============================================================================

command="${1:-help}"
shift 2>/dev/null || true

case "$command" in
    jobs)       cmd_jobs ;;
    search)     cmd_search "$@" ;;
    status)     cmd_status "$@" ;;
    build)      cmd_build "$@" ;;
    log)        cmd_log "$@" ;;
    queue)      cmd_queue ;;
    info)       cmd_info "$@" ;;
    mybuilds)   cmd_mybuilds "$@" ;;
    running)    cmd_running ;;
    help|--help|-h) cmd_help ;;
    *)
        echo "Unknown command: $command"
        echo "Run '$0 help' for usage"
        exit 1
        ;;
esac
