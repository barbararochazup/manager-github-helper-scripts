import os
import requests
from dateutil import parser
import re
import csv
from collections import Counter, defaultdict

# =========================
# CONFIG
# =========================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise Exception("Defina a variável de ambiente GITHUB_TOKEN com seu token de acesso do GitHub.")

API_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

PROJECT_URL = "https://github.com/orgs/stack-spot/projects/251"  

# Range de datas (inclusive)
START_DATE = "2025-10-07"
END_DATE   = "2025-12-10"

KIND_FIELD = "Kind"
TYPE_FIELD = "Type"
SCOPE_FIELD = "Scope"  

# =========================
# Funções auxiliares
# =========================
def run_query(query, variables):
    response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Erro na API GitHub: {response.status_code}, {response.text}")
    data = response.json()
    if "errors" in data:
        raise Exception(f"Erro GraphQL: {data['errors']}")
    return data

def get_project_id_from_url(url):
    m = re.search(r"github.com/(orgs|users)/([^/]+)/projects/(\d+)", url)
    if not m:
        raise ValueError(f"URL inválida de project: {url}")
    entity_type, entity_name, number = m.groups()
    if entity_type == "orgs":
        query = """
        query($org: String!, $number: Int!) {
            organization(login: $org) {
                projectV2(number: $number) { id title }
            }
        }
        """
        variables = {"org": entity_name, "number": int(number)}
        data = run_query(query, variables)
        return data["data"]["organization"]["projectV2"]["id"], data["data"]["organization"]["projectV2"]["title"]
    else:
        query = """
        query($user: String!, $number: Int!) {
            user(login: $user) {
                projectV2(number: $number) { id title }
            }
        }
        """
        variables = {"user": entity_name, "number": int(number)}
        data = run_query(query, variables)
        return data["data"]["user"]["projectV2"]["id"], data["data"]["user"]["projectV2"]["title"]

def get_project_items(project_id):
    query = """
    query($projectId: ID!, $cursor: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 50, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              content {
                ... on Issue {
                  id number title closedAt state
                  repository { nameWithOwner }
                  labels(first: 20) { nodes { name } }
                  issueType { name }
                  parent { ... on Issue { number title repository { nameWithOwner } } }
                  assignees(first: 20) { nodes { login } }
                }
              }
              fieldValues(first: 20) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    field { ... on ProjectV2FieldCommon { name } }
                    name
                  }
                  ... on ProjectV2ItemFieldTextValue {
                    field { ... on ProjectV2FieldCommon { name } }
                    text
                  }
                  ... on ProjectV2ItemFieldNumberValue {
                    field { ... on ProjectV2FieldCommon { name } }
                    number
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    results = []
    cursor = None
    while True:
        data = run_query(query, {"projectId": project_id, "cursor": cursor})
        items = data["data"]["node"]["items"]
        results.extend(items["nodes"])
        if not items["pageInfo"]["hasNextPage"]:
            break
        cursor = items["pageInfo"]["endCursor"]
    return results

def extract_type(item):
    kind_value = None
    type_value = None
    if "fieldValues" in item and "nodes" in item["fieldValues"]:
        for field in item["fieldValues"]["nodes"]:
            if not field or "field" not in field or not field["field"]:
                continue
            field_name = field["field"].get("name", "").strip().lower()
            field_value = field.get("name") or field.get("text") or (
                str(field["number"]) if "number" in field and field["number"] is not None else None
            )
            if not field_value:
                continue
            if field_name == KIND_FIELD.lower():
                kind_value = field_value
            elif field_name == TYPE_FIELD.lower():
                type_value = field_value
    if kind_value:
        return kind_value
    if type_value:
        return type_value
    issue = item.get("content")
    if issue and "issueType" in issue and issue["issueType"]:
        return issue["issueType"].get("name") or "Desconhecido"
    return "Desconhecido"

def extract_scope(item):
    if "fieldValues" in item and "nodes" in item["fieldValues"]:
        for field in item["fieldValues"]["nodes"]:
            if not field or "field" not in field or not field["field"]:
                continue
            field_name = field["field"].get("name", "").strip().lower()
            field_value = field.get("name") or field.get("text") or (
                str(field["number"]) if "number" in field and field["number"] is not None else None
            )
            if not field_value:
                continue
            if field_name == SCOPE_FIELD.lower():
                return field_value
    return "Sem Scope"

def extract_assignees(item):
    issue = item.get("content")
    if issue and "assignees" in issue and issue["assignees"] and "nodes" in issue["assignees"]:
        return [a["login"] for a in issue["assignees"]["nodes"] if a and a.get("login")]
    return []

# =========================
# Execução principal
# =========================
if __name__ == "__main__":
    project_id, project_title = get_project_id_from_url(PROJECT_URL)
    print(f"\nProject: {project_title} (ID: {project_id})")
    items = get_project_items(project_id)
    print(f"Total items: {len(items)}")

    # Agrupar por tipo (dentro do range)
    filtered_issues = []
    for item in items:
        issue = item.get("content")
        if not issue or not issue.get("closedAt"):
            continue
        closed = parser.isoparse(issue["closedAt"])
        # Filtrar pelo range de datas (inclusive)
        if not (START_DATE <= closed.date().isoformat() <= END_DATE):
            continue

        tipo = extract_type(item)
        scope = extract_scope(item)
        assignees = extract_assignees(item)
        issue_dict = {
            "project": project_title,
            "scope": scope,
            "type": tipo,
            "repo": issue['repository']['nameWithOwner'],
            "number": issue['number'],
            "title": issue['title'],
            "state": issue['state'],
            "closedAt": issue['closedAt'],
            "parent_number": issue["parent"]["number"] if issue.get("parent") else "",
            "parent_title": issue["parent"]["title"] if issue.get("parent") else "",
            "assignees": assignees,
        }
        filtered_issues.append(issue_dict)

    # Agrupar por tipo e contar pessoas distintas por tipo
    type_to_issues = defaultdict(list)
    for i in filtered_issues:
        type_to_issues[i["type"]].append(i)

    total_issues = len(filtered_issues)
    md_lines = []
    md_lines.append(f"Total de issues fechadas: {total_issues}\n")

    for t, issues in type_to_issues.items():
        count = len(issues)
        perc = 100.0 * count / total_issues if total_issues else 0.0
        # Pessoas distintas que trabalharam nas issues desse tipo (assignees únicos)
        all_people = set()
        for i in issues:
            all_people.update(i["assignees"])
        md_lines.append(f"{t}: {count} ({perc:.1f}%) - Qtd de Pessoas: {len(all_people)}")

    # Salvar CSV com todas as issues do período filtrado
    csv_filename = f"{project_title.replace(' ', '_')}_{START_DATE}_a_{END_DATE}.csv"
    with open(csv_filename, "w", newline='', encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            "project", "scope", "type", "repo", "number", "title", "state", "closedAt", 
            "parent_number", "parent_title", "assignees"
        ])
        writer.writeheader()
        for issue in filtered_issues:
            row = dict(issue)
            row['assignees'] = ", ".join(issue['assignees'])
            writer.writerow(row)
    md_lines.append(f"\n_CSV salvo: `{csv_filename}`_\n")

    # Salvar relatório em Markdown
    with open("relatorio.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print("\nRelatório Markdown salvo em: relatorio.md")
