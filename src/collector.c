#define _POSIX_C_SOURCE 200809L
#define _XOPEN_SOURCE 700
#include <ctype.h>
#include <errno.h>
#include <glob.h>
#include <json-c/json.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define HISTORY 90
#define MAX_GPUS 16
static const char *keys[] = {"cpu", "gpu", "ram", "vram"};
static const char *defaults = "{\"interval\":1.0,\"visible\":{\"cpu\":true,\"gpu\":true,\"ram\":true,\"vram\":true},"
    "\"colors\":{\"cpu\":\"#67b5ff\",\"gpu\":\"#ab92ff\",\"ram\":\"#57d6b2\",\"vram\":\"#ffbe70\"},"
    "\"absolute\":true,\"mini\":\"bars\",\"history\":true,\"gpu\":\"\",\"opacity\":0.97,"
    "\"appearance\":\"system\",\"alerts\":false,\"threshold\":90,\"autostart\":true}";
static volatile sig_atomic_t stopping;
static char config_path[PATH_MAX], state_path[PATH_MAX], proc_root[PATH_MAX];
static struct timespec config_mtime = {-1, 0};
static json_object *config;
static double history[4][HISTORY];
static unsigned long sequence;
static char cpu_temperature_paths[16][PATH_MAX];
static size_t cpu_temperature_count;
static size_t history_count, history_head;

static void stop(int signal_number) { (void)signal_number; stopping = 1; }
static void add(json_object *object, const char *key, json_object *value) {
    json_object_object_add(object, key, value);
}
static json_object *field(json_object *object, const char *key) {
    json_object *value = NULL;
    json_object_object_get_ex(object, key, &value);
    return value;
}
static json_object *decimal(double value) {
    return isfinite(value) ? json_object_new_double(value) : NULL;
}
static double clamp(double value, double low, double high) {
    return isfinite(value) ? fmax(low, fmin(high, value)) : low;
}
static bool hex_color(const char *text) {
    if (!text || strlen(text) != 7 || text[0] != '#') return false;
    for (size_t i = 1; i < 7; i++) if (!isxdigit((unsigned char)text[i])) return false;
    return true;
}

static void load_config(void) {
    struct stat info;
    bool exists = stat(config_path, &info) == 0;
    struct timespec modified = exists ? info.st_mtim : (struct timespec){0, 0};
    if (config && modified.tv_sec == config_mtime.tv_sec && modified.tv_nsec == config_mtime.tv_nsec) return;
    config_mtime = modified;
    json_object *next = json_tokener_parse(defaults);
    json_object *saved = exists ? json_object_from_file(config_path) : NULL;
    if (saved && json_object_is_type(saved, json_type_object)) {
        json_object_object_foreach(next, key, fallback) {
            json_object *value = field(saved, key);
            if (!value) continue;
            if (json_object_is_type(fallback, json_type_object)) {
                if (!json_object_is_type(value, json_type_object)) continue;
                json_object_object_foreach(fallback, child, initial) {
                    json_object *replacement = field(value, child);
                    if (replacement && json_object_get_type(replacement) == json_object_get_type(initial)) {
                        if (strcmp(key, "colors") == 0 && !hex_color(json_object_get_string(replacement))) continue;
                        add(fallback, child, json_object_get(replacement));
                    }
                }
            } else if (json_object_get_type(value) == json_object_get_type(fallback) ||
                       ((strcmp(key, "interval") == 0 || strcmp(key, "opacity") == 0) &&
                        (json_object_is_type(value, json_type_int) || json_object_is_type(value, json_type_double)))) {
                add(next, key, json_object_get(value));
            }
        }
    }
    if (saved) json_object_put(saved);
    add(next, "interval", decimal(clamp(json_object_get_double(field(next, "interval")), 0.5, 30)));
    add(next, "opacity", decimal(clamp(json_object_get_double(field(next, "opacity")), 0.5, 1)));
    add(next, "threshold", json_object_new_int((int)clamp(json_object_get_double(field(next, "threshold")), 1, 100)));
    const char *mini = json_object_get_string(field(next, "mini"));
    if (strcmp(mini, "bars") && strcmp(mini, "graphs")) add(next, "mini", json_object_new_string("bars"));
    const char *appearance = json_object_get_string(field(next, "appearance"));
    if (strcmp(appearance, "system") && strcmp(appearance, "light") && strcmp(appearance, "dark"))
        add(next, "appearance", json_object_new_string("system"));
    if (config) json_object_put(config);
    config = next;
}

static double read_number(const char *device, const char *name) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", device, name) >= (int)sizeof path) return NAN;
    FILE *file = fopen(path, "r");
    if (!file) return NAN;
    unsigned long long number;
    int count = fscanf(file, "%llu", &number);
    fclose(file);
    return count == 1 ? (double)number : NAN;
}

static void temperature_path(const char *directory, bool cpu, char output[PATH_MAX]) {
    char pattern[PATH_MAX];
    output[0] = 0;
    if (snprintf(pattern, sizeof pattern, "%s/temp1_input", directory) >= (int)sizeof pattern) return;
    if (access(pattern, R_OK) == 0) snprintf(output, PATH_MAX, "%s", pattern);
    if (snprintf(pattern, sizeof pattern, "%s/temp*_label", directory) >= (int)sizeof pattern) return;
    glob_t labels;
    int best = 0;
    if (glob(pattern, 0, NULL, &labels) != 0) return;
    for (size_t i = 0; i < labels.gl_pathc; i++) {
        FILE *file = fopen(labels.gl_pathv[i], "r");
        char label[128];
        if (!file) continue;
        bool read = fgets(label, sizeof label, file) != NULL;
        fclose(file);
        if (!read) continue;
        int score = 0;
        if (cpu) {
            if (strncmp(label, "Package id", 10) == 0 || strncmp(label, "Tdie", 4) == 0) score = 3;
            else if (strncmp(label, "Tctl", 4) == 0) score = 2;
        } else if (strncmp(label, "edge", 4) == 0) score = 3;
        if (score > best) {
            snprintf(pattern, sizeof pattern, "%s", labels.gl_pathv[i]);
            char *suffix = strrchr(pattern, '_');
            if (!suffix) continue;
            strcpy(suffix, "_input");
            if (access(pattern, R_OK) == 0) {
                snprintf(output, PATH_MAX, "%s", pattern);
                best = score;
            }
        }
    }
    globfree(&labels);
}

static void discover_cpu_temperatures(void) {
    glob_t monitors;
    const char *pattern = getenv("FRANCOS_HWMON_GLOB");
    if (!pattern) pattern = "/sys/class/hwmon/hwmon*";
    if (glob(pattern, 0, NULL, &monitors) != 0) return;
    for (size_t i = 0; i < monitors.gl_pathc && cpu_temperature_count < 16; i++) {
        char path[PATH_MAX], name[64];
        if (snprintf(path, sizeof path, "%s/name", monitors.gl_pathv[i]) >= (int)sizeof path) continue;
        FILE *file = fopen(path, "r");
        if (!file) continue;
        bool read = fgets(name, sizeof name, file) != NULL;
        fclose(file);
        if (!read) continue;
        name[strcspn(name, "\r\n")] = 0;
        if (strcmp(name, "coretemp") && strcmp(name, "k10temp") && strcmp(name, "zenpower")) continue;
        temperature_path(monitors.gl_pathv[i], true, cpu_temperature_paths[cpu_temperature_count]);
        if (cpu_temperature_paths[cpu_temperature_count][0]) cpu_temperature_count++;
    }
    globfree(&monitors);
}

static double temperature(const char *path) {
    if (!path || !*path) return NAN;
    FILE *file = fopen(path, "r");
    if (!file) return NAN;
    long millidegrees;
    int parsed = fscanf(file, "%ld", &millidegrees);
    fclose(file);
    if (parsed != 1 || millidegrees < -40000 || millidegrees > 150000) return NAN;
    return millidegrees / 1000.0;
}

static json_object *discover_gpus(void) {
    json_object *devices = json_object_new_array();
    glob_t cards;
    const char *pattern = getenv("FRANCOS_DRM_GLOB");
    if (!pattern) pattern = "/sys/class/drm/card[0-9]*";
    if (glob(pattern, 0, NULL, &cards) != 0) return devices;
    for (size_t i = 0; i < cards.gl_pathc && json_object_array_length(devices) < MAX_GPUS; i++) {
        const char *name = strrchr(cards.gl_pathv[i], '/');
        name = name ? name + 1 : cards.gl_pathv[i];
        const char *digit = name + 4;
        if (strncmp(name, "card", 4) || !isdigit((unsigned char)*digit)) continue;
        while (isdigit((unsigned char)*digit)) digit++;
        if (*digit) continue;
        char device[PATH_MAX], path[PATH_MAX], resolved[PATH_MAX];
        if (snprintf(device, sizeof device, "%s/device", cards.gl_pathv[i]) >= (int)sizeof device) continue;
        if (snprintf(path, sizeof path, "%s/vendor", device) >= (int)sizeof path) continue;
        FILE *file = fopen(path, "r");
        unsigned vendor = 0;
        if (!file) continue;
        int parsed = fscanf(file, "%x", &vendor);
        fclose(file);
        if (parsed != 1 || vendor != 0x1002 || !realpath(device, resolved)) continue;
        char pci[64];
        snprintf(pci, sizeof pci, "%s", strrchr(resolved, '/') + 1);
        char driver[128] = "indisponível";
        if (snprintf(path, sizeof path, "%s/driver", device) >= (int)sizeof path) continue;
        if (realpath(path, resolved)) snprintf(driver, sizeof driver, "%s", strrchr(resolved, '/') + 1);
        char product[512] = "AMD Radeon";
        if (snprintf(path, sizeof path, "%s/product_name", device) >= (int)sizeof path) continue;
        file = fopen(path, "r");
        if (file) {
            if (!fgets(product, sizeof product, file)) snprintf(product, sizeof product, "AMD Radeon");
            fclose(file);
        } else if (strspn(pci, "0123456789abcdefABCDEF:.") == strlen(pci)) {
            char command[128], line[1024];
            snprintf(command, sizeof command, "/usr/bin/lspci -s %s 2>/dev/null", pci);
            FILE *pipe = popen(command, "r");
            if (pipe) {
                if (fgets(line, sizeof line, pipe)) {
                    char *description = strstr(line, ": ");
                    snprintf(product, sizeof product, "%.511s", description ? description + 2 : line);
                }
                pclose(pipe);
            }
        }
        product[strcspn(product, "\r\n")] = 0;
        json_object *gpu = json_object_new_object();
        add(gpu, "path", json_object_new_string(device));
        add(gpu, "pci", json_object_new_string(pci));
        add(gpu, "name", json_object_new_string(product));
        add(gpu, "driver", json_object_new_string(driver));
        char monitor_pattern[PATH_MAX], sensor[PATH_MAX] = "";
        if (snprintf(monitor_pattern, sizeof monitor_pattern, "%s/hwmon/hwmon*", device) < (int)sizeof monitor_pattern) {
            glob_t monitors;
            if (glob(monitor_pattern, 0, NULL, &monitors) == 0) {
                if (monitors.gl_pathc) temperature_path(monitors.gl_pathv[0], false, sensor);
                globfree(&monitors);
            }
        }
        add(gpu, "temperature_path", json_object_new_string(sensor));
        json_object_array_add(devices, gpu);
    }
    globfree(&cards);
    return devices;
}

static FILE *open_proc(const char *name) {
    char path[PATH_MAX];
    if (snprintf(path, sizeof path, "%s/%s", proc_root, name) >= (int)sizeof path) return NULL;
    return fopen(path, "r");
}

static json_object *cpu_identity(void) {
    FILE *file = open_proc("cpuinfo");
    char line[1024], name[512] = "CPU";
    unsigned threads = 0, cores = 0;
    int sockets[4096], core_ids[4096], socket = 0, core = -1;
    if (file) {
        while (fgets(line, sizeof line, file)) {
            if (strncmp(line, "model name", 10) == 0 && strcmp(name, "CPU") == 0) {
                char *value = strchr(line, ':');
                if (value) snprintf(name, sizeof name, "%.511s", value + 2);
                name[strcspn(name, "\r\n")] = 0;
            }
            if (strncmp(line, "processor", 9) == 0) threads++;
            if (sscanf(line, "physical id : %d", &socket) == 1) continue;
            if (sscanf(line, "core id : %d", &core) == 1 && cores < 4096) {
                bool seen = false;
                for (unsigned i = 0; i < cores; i++) if (sockets[i] == socket && core_ids[i] == core) seen = true;
                if (!seen) { sockets[cores] = socket; core_ids[cores++] = core; }
            }
        }
        fclose(file);
    }
    json_object *cpu = json_object_new_object();
    add(cpu, "name", json_object_new_string(name));
    add(cpu, "threads", json_object_new_int(threads));
    add(cpu, "cores", json_object_new_int(cores ? cores : threads));
    return cpu;
}

static double cpu_usage(void) {
    static uint64_t previous_total, previous_idle;
    static bool have_previous;
    FILE *file = open_proc("stat");
    if (!file) return NAN;
    unsigned long long v[8] = {0};
    int count = fscanf(file, "cpu %llu %llu %llu %llu %llu %llu %llu %llu",
                       &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]);
    fclose(file);
    if (count < 4) return NAN;
    uint64_t total = 0, idle = v[3] + v[4];
    for (int i = 0; i < 8; i++) total += v[i];
    double usage = NAN;
    if (have_previous && total > previous_total && idle >= previous_idle)
        usage = clamp(100.0 * (1 - (double)(idle - previous_idle) / (total - previous_total)), 0, 100);
    previous_total = total;
    previous_idle = idle;
    have_previous = true;
    return usage;
}

static json_object *memory(double used, double total) {
    json_object *object = json_object_new_object();
    add(object, "used", decimal(used));
    add(object, "total", decimal(total));
    add(object, "percent", decimal(total > 0 ? used / total * 100 : NAN));
    return object;
}

static json_object *ram_usage(void) {
    FILE *file = open_proc("meminfo");
    double total = NAN, available = NAN;
    char line[256];
    if (file) {
        while (fgets(line, sizeof line, file)) {
            unsigned long long value;
            if (sscanf(line, "MemTotal: %llu kB", &value) == 1) total = (double)value * 1024;
            else if (sscanf(line, "MemAvailable: %llu kB", &value) == 1) available = (double)value * 1024;
        }
        fclose(file);
    }
    return memory(isfinite(available) ? fmax(0, total - available) : NAN, total);
}

static json_object *sample(json_object *cpu, json_object *devices) {
    json_object *selected = NULL;
    const char *wanted = json_object_get_string(field(config, "gpu"));
    size_t count = json_object_array_length(devices);
    for (size_t i = 0; i < count; i++) {
        json_object *candidate = json_object_array_get_idx(devices, i);
        if (!selected) selected = candidate;
        if (strcmp(wanted, json_object_get_string(field(candidate, "pci"))) == 0) { selected = candidate; break; }
    }
    double busy = NAN, used = NAN, total = NAN;
    if (selected) {
        const char *path = json_object_get_string(field(selected, "path"));
        busy = read_number(path, "gpu_busy_percent");
        used = read_number(path, "mem_info_vram_used");
        total = read_number(path, "mem_info_vram_total");
    }
    json_object *ram = ram_usage(), *vram = memory(used, total);
    double values[4] = {cpu_usage(), busy, NAN, NAN};
    json_object *ram_percent = field(ram, "percent"), *vram_percent = field(vram, "percent");
    if (ram_percent) values[2] = json_object_get_double(ram_percent);
    if (vram_percent) values[3] = json_object_get_double(vram_percent);
    for (int k = 0; k < 4; k++) history[k][history_head] = values[k];
    history_head = (history_head + 1) % HISTORY;
    if (history_count < HISTORY) history_count++;
    struct timespec now;
    clock_gettime(CLOCK_REALTIME, &now);
    json_object *root = json_object_new_object(), *metrics = json_object_new_object(), *histories = json_object_new_object();
    add(root, "timestamp", decimal(now.tv_sec + now.tv_nsec / 1e9));
    add(root, "sequence", json_object_new_int64(++sequence));
    double cpu_temp = NAN;
    for (size_t i = 0; i < cpu_temperature_count; i++) {
        double reading = temperature(cpu_temperature_paths[i]);
        if (isfinite(reading) && (!isfinite(cpu_temp) || reading > cpu_temp)) cpu_temp = reading;
    }
    json_object *temperatures = json_object_new_object();
    add(temperatures, "cpu", decimal(cpu_temp));
    add(temperatures, "gpu", decimal(selected ? temperature(json_object_get_string(field(selected, "temperature_path"))) : NAN));
    add(root, "temperatures", temperatures);
    add(root, "cpu", json_object_get(cpu));
    add(root, "gpu", selected ? json_object_get(selected) : NULL);
    add(root, "gpus", json_object_get(devices));
    add(root, "ram", ram);
    add(root, "vram", vram);
    add(root, "settings", json_object_get(config));
    for (int k = 0; k < 4; k++) {
        add(metrics, keys[k], decimal(values[k]));
        json_object *array = json_object_new_array_ext((int)history_count);
        for (size_t i = 0; i < history_count; i++)
            json_object_array_add(array, decimal(history[k][(history_head + HISTORY - history_count + i) % HISTORY]));
        add(histories, keys[k], array);
    }
    add(root, "values", metrics);
    add(root, "history", histories);
    return root;
}

int main(int argc, char **argv) {
    bool once = argc == 2 && strcmp(argv[1], "--once") == 0;
    const char *home = getenv("HOME"), *runtime = getenv("XDG_RUNTIME_DIR");
    if (!home) return 1;
    snprintf(config_path, sizeof config_path, "%s/.config/francos-system-monitor/settings.json", home);
    if (runtime) snprintf(state_path, sizeof state_path, "%s/francos-system-monitor.json", runtime);
    else snprintf(state_path, sizeof state_path, "/run/user/%u/francos-system-monitor.json", getuid());
    const char *test_proc = getenv("FRANCOS_PROC_ROOT");
    snprintf(proc_root, sizeof proc_root, "%s", test_proc ? test_proc : "/proc");
    char lock_path[PATH_MAX], temporary[PATH_MAX];
    if (snprintf(lock_path, sizeof lock_path, "%s.lock", state_path) >= (int)sizeof lock_path ||
        snprintf(temporary, sizeof temporary, "%s.tmp", state_path) >= (int)sizeof temporary) return 1;
    FILE *lock = NULL;
    if (!once) {
        lock = fopen(lock_path, "a");
        if (!lock) { perror("lock"); return 1; }
        if (flock(fileno(lock), LOCK_EX | LOCK_NB)) { fclose(lock); return 0; }
    }
    signal(SIGTERM, stop);
    signal(SIGINT, stop);
    discover_cpu_temperatures();
    json_object *cpu = cpu_identity(), *devices = discover_gpus();
    while (!stopping) {
        struct timespec deadline;
        clock_gettime(CLOCK_MONOTONIC, &deadline);
        load_config();
        json_object *data = sample(cpu, devices);
        const char *text = json_object_to_json_string_ext(data, JSON_C_TO_STRING_PLAIN);
        if (once) { puts(text); json_object_put(data); break; }
        FILE *output = fopen(temporary, "w");
        if (output) {
            size_t length = strlen(text);
            bool written = fwrite(text, 1, length, output) == length;
            if (fclose(output) != 0) written = false;
            if (written && rename(temporary, state_path) != 0) perror("snapshot rename");
        } else perror("snapshot write");
        json_object_put(data);
        double interval = json_object_get_double(field(config, "interval"));
        deadline.tv_sec += (time_t)interval;
        deadline.tv_nsec += (long)((interval - (time_t)interval) * 1e9);
        if (deadline.tv_nsec >= 1000000000L) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000L; }
        while (!stopping && clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL) == EINTR) {}
    }
    json_object_put(cpu);
    json_object_put(devices);
    if (config) json_object_put(config);
    if (lock) fclose(lock);
    return 0;
}
