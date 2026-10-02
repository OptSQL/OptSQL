#include <sqlite3.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void json_string(FILE *out, const char *value) {
    fputc('"', out);
    if (value != NULL) {
        for (const unsigned char *p = (const unsigned char *)value; *p; p++) {
            switch (*p) {
                case '\\':
                    fputs("\\\\", out);
                    break;
                case '"':
                    fputs("\\\"", out);
                    break;
                case '\b':
                    fputs("\\b", out);
                    break;
                case '\f':
                    fputs("\\f", out);
                    break;
                case '\n':
                    fputs("\\n", out);
                    break;
                case '\r':
                    fputs("\\r", out);
                    break;
                case '\t':
                    fputs("\\t", out);
                    break;
                default:
                    if (*p < 0x20) {
                        fprintf(out, "\\u%04x", *p);
                    } else {
                        fputc(*p, out);
                    }
                    break;
            }
        }
    }
    fputc('"', out);
}

static void print_error_json(const char *code, const char *message) {
    printf("{\"available\":false,\"error_code\":");
    json_string(stdout, code);
    printf(",\"error_message\":");
    json_string(stdout, message);
    printf("}\n");
}

static int enable_scanstatus(sqlite3 *db, char *message, size_t message_size) {
#ifdef SQLITE_DBCONFIG_STMT_SCANSTATUS
    int is_enabled = 0;
    int rc = sqlite3_db_config(db, SQLITE_DBCONFIG_STMT_SCANSTATUS, 1, &is_enabled);
    if (rc != SQLITE_OK) {
        snprintf(message, message_size, "%s", sqlite3_errmsg(db));
        return rc;
    }
    if (!is_enabled) {
        snprintf(message, message_size, "SQLITE_DBCONFIG_STMT_SCANSTATUS did not enable scanstatus");
        return SQLITE_ERROR;
    }
    return SQLITE_OK;
#else
    snprintf(message, message_size, "SQLite headers do not expose SQLITE_DBCONFIG_STMT_SCANSTATUS");
    return SQLITE_ERROR;
#endif
}

static int scanstatus_int64(sqlite3_stmt *stmt, int idx, int op, sqlite3_int64 *out) {
#ifdef SQLITE_SCANSTAT_COMPLEX
    return sqlite3_stmt_scanstatus_v2(stmt, idx, op, 0, out);
#else
    return sqlite3_stmt_scanstatus(stmt, idx, op, out);
#endif
}

static int scanstatus_int(sqlite3_stmt *stmt, int idx, int op, int *out) {
#ifdef SQLITE_SCANSTAT_COMPLEX
    return sqlite3_stmt_scanstatus_v2(stmt, idx, op, 0, out);
#else
    return sqlite3_stmt_scanstatus(stmt, idx, op, out);
#endif
}

static int scanstatus_double(sqlite3_stmt *stmt, int idx, int op, double *out) {
#ifdef SQLITE_SCANSTAT_COMPLEX
    return sqlite3_stmt_scanstatus_v2(stmt, idx, op, 0, out);
#else
    return sqlite3_stmt_scanstatus(stmt, idx, op, out);
#endif
}

static int scanstatus_text(sqlite3_stmt *stmt, int idx, int op, const char **out) {
#ifdef SQLITE_SCANSTAT_COMPLEX
    return sqlite3_stmt_scanstatus_v2(stmt, idx, op, 0, out);
#else
    return sqlite3_stmt_scanstatus(stmt, idx, op, out);
#endif
}

int main(int argc, char **argv) {
    if (argc != 3) {
        print_error_json("usage", "usage: scanstatus_probe <sqlite-db-path> <select-sql>");
        return 2;
    }

    const char *db_path = argv[1];
    const char *sql = argv[2];
    sqlite3 *db = NULL;
    sqlite3_stmt *stmt = NULL;

    int rc = sqlite3_open_v2(db_path, &db, SQLITE_OPEN_READONLY, NULL);
    if (rc != SQLITE_OK) {
        print_error_json("open_failed", db ? sqlite3_errmsg(db) : "sqlite3_open_v2 failed");
        if (db) {
            sqlite3_close(db);
        }
        return 1;
    }

    char enable_message[512] = {0};
    rc = enable_scanstatus(db, enable_message, sizeof(enable_message));
    if (rc != SQLITE_OK) {
        print_error_json("scanstatus_unavailable", enable_message);
        sqlite3_close(db);
        return 1;
    }

    rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        print_error_json("prepare_failed", sqlite3_errmsg(db));
        sqlite3_close(db);
        return 1;
    }

    sqlite3_int64 result_rows = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        result_rows++;
    }
    if (rc != SQLITE_DONE) {
        print_error_json("step_failed", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        sqlite3_close(db);
        return 1;
    }

    sqlite3_int64 total_nvisit = 0;
    int detail_count = 0;
    printf("{\"available\":true,\"scan_row_kind\":\"actual\",");
    printf("\"scan_row_source\":\"sqlite_stmt_scanstatus_v2_nvisit\",");
    printf("\"result_rows\":%lld,", (long long)result_rows);
    printf("\"scan_details\":[");
    for (int idx = 0;; idx++) {
        sqlite3_int64 nvisit = -1;
        if (scanstatus_int64(stmt, idx, SQLITE_SCANSTAT_NVISIT, &nvisit) != SQLITE_OK) {
            break;
        }

        sqlite3_int64 nloop = -1;
        sqlite3_int64 ncycle = -1;
        int select_id = -1;
        int parent_id = -1;
        double estimate = -1.0;
        const char *name = NULL;
        const char *explain = NULL;

        (void)scanstatus_int64(stmt, idx, SQLITE_SCANSTAT_NLOOP, &nloop);
        (void)scanstatus_int64(stmt, idx, SQLITE_SCANSTAT_NCYCLE, &ncycle);
        (void)scanstatus_int(stmt, idx, SQLITE_SCANSTAT_SELECTID, &select_id);
#ifdef SQLITE_SCANSTAT_PARENTID
        (void)scanstatus_int(stmt, idx, SQLITE_SCANSTAT_PARENTID, &parent_id);
#endif
        (void)scanstatus_double(stmt, idx, SQLITE_SCANSTAT_EST, &estimate);
        (void)scanstatus_text(stmt, idx, SQLITE_SCANSTAT_NAME, &name);
        (void)scanstatus_text(stmt, idx, SQLITE_SCANSTAT_EXPLAIN, &explain);

        if (detail_count > 0) {
            printf(",");
        }
        printf("{\"loop_index\":%d,\"select_id\":%d,\"parent_id\":%d,", idx, select_id, parent_id);
        printf("\"name\":");
        json_string(stdout, name);
        printf(",\"explain\":");
        json_string(stdout, explain);
        printf(",\"nloop\":%lld,\"nvisit\":%lld,\"est\":%.17g,\"ncycle\":%lld}",
               (long long)nloop,
               (long long)nvisit,
               estimate,
               (long long)ncycle);
        total_nvisit += nvisit > 0 ? nvisit : 0;
        detail_count++;
    }
    printf("],\"total_scanned_rows\":%lld,\"detail_count\":%d}\n",
           (long long)total_nvisit,
           detail_count);

    sqlite3_finalize(stmt);
    sqlite3_close(db);
    return detail_count > 0 ? 0 : 1;
}
