/* Admin Toolkit page behaviour. Everything is opt-in through data-aat-* attributes. */
(() => {
    "use strict";

    const ACTIVE_LOG_STATES = new Set(["PENDING", "RUNNING"]);

    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        return node;
    };

    const storage = {
        get(key) {
            try {
                return window.localStorage.getItem(key);
            } catch (e) {
                return null;
            }
        },
        set(key, value) {
            try {
                window.localStorage.setItem(key, value);
            } catch (e) {
                // Storage can be unavailable (private mode, blocked site data); tab memory is optional.
            }
        },
    };

    const fetchJson = async (url) => {
        const response = await fetch(url, {
            credentials: "same-origin",
            headers: {"Accept": "application/json"},
        });
        if (!response.ok) {
            throw new Error(`${response.status} ${response.statusText}`);
        }
        return response.json();
    };

    /* Repeats `fn` every `ms` while the tab is visible, and right away when it becomes visible again. */
    const poll = (fn, ms) => {
        let timer = null;
        const run = async () => {
            window.clearTimeout(timer);
            if (document.visibilityState === "visible") {
                await fn();
            }
            timer = window.setTimeout(run, ms);
        };
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") {
                run();
            }
        });
        run();
    };

    // ------------------------------------------------------------------ dashboard

    const formatMegabytes = (mb) => {
        const value = Number(mb) || 0;
        if (value >= 1024 * 1024) {
            return `${(value / 1024 / 1024).toFixed(2)} TB`;
        }
        if (value >= 1024) {
            return `${(value / 1024).toFixed(2)} GB`;
        }
        return `${value.toFixed(1)} MB`;
    };

    const formatUptime = (hours) => {
        const totalMinutes = Math.round((Number(hours) || 0) * 60);
        const days = Math.floor(totalMinutes / 1440);
        const h = Math.floor((totalMinutes % 1440) / 60);
        const m = totalMinutes % 60;
        if (days > 0) {
            return `${days}d ${h}h`;
        }
        if (h > 0) {
            return `${h}h ${m}m`;
        }
        return `${m}m`;
    };

    const usageClass = (percent) => {
        if (percent >= 90) {
            return "bg-danger";
        }
        if (percent >= 75) {
            return "bg-warning";
        }
        return "bg-success";
    };

    const initDashboard = (root) => {
        const setStat = (name, value) => {
            root.querySelectorAll(`[data-stat="${name}"]`).forEach((node) => {
                node.textContent = value;
            });
        };

        const setBar = (name, percent) => {
            const value = Math.max(0, Math.min(100, Number(percent) || 0));
            const bar = root.querySelector(`[data-bar="${name}"]`);
            const wrap = root.querySelector(`[data-bar-wrap="${name}"]`);
            if (bar) {
                bar.style.width = `${value}%`;
                bar.classList.remove("bg-success", "bg-warning", "bg-danger");
                bar.classList.add(usageClass(value));
            }
            if (wrap) {
                wrap.setAttribute("aria-valuenow", String(value));
            }
        };

        const updated = root.querySelector("[data-aat-updated]");
        const liveDot = root.querySelector("[data-aat-live-dot]");
        const errorBox = root.querySelector("[data-aat-stats-error]");
        let lastUpdate = null;

        const renderAge = () => {
            if (!updated || lastUpdate === null) {
                return;
            }
            const seconds = Math.round((Date.now() - lastUpdate) / 1000);
            updated.textContent = seconds < 2 ? "Updated just now" : `Updated ${seconds}s ago`;
        };
        window.setInterval(renderAge, 1000);

        const loadStats = async () => {
            try {
                const data = await fetchJson(root.dataset.statsUrl);
                setStat("cpu", `${Number(data.cpu).toFixed(1)}%`);
                setBar("cpu", data.cpu);
                setStat("load", data.load ? `Load ${data.load}` : "");
                setStat("load_full", data.load || "—");

                setStat("mem", `${Number(data.mem_percent).toFixed(1)}%`);
                setBar("mem", data.mem_percent);
                setStat("mem_detail", `${data.mem_used} GB of ${data.mem_total} GB`);

                setStat("disk", `${Number(data.disk_percent).toFixed(1)}%`);
                setBar("disk", data.disk_percent);
                setStat("disk_detail", `${data.disk_used} GB of ${data.disk_total} GB`);

                setStat("queue", Number(data.queue).toLocaleString());
                setStat("uptime", formatUptime(data.uptime));
                setStat("net_sent", formatMegabytes(data.net_sent));
                setStat("net_recv", formatMegabytes(data.net_recv));
                setStat("users", Number(data.users).toLocaleString());
                setStat("characters", Number(data.characters).toLocaleString());
                setStat("db_size", data.db_size > 0 ? formatMegabytes(data.db_size) : "Unknown");

                lastUpdate = Date.now();
                renderAge();
                errorBox?.classList.add("d-none");
                liveDot?.classList.replace("bg-danger", "bg-success");
            } catch (error) {
                errorBox?.classList.remove("d-none");
                liveDot?.classList.replace("bg-success", "bg-danger");
                if (updated) {
                    updated.textContent = "Connection lost";
                }
            }
        };

        const serviceTile = (service) => {
            const state = String(service.state || "unknown").toLowerCase();
            const health = String(service.health || "").toLowerCase();
            let tone = "secondary";
            if (service.status === "Up") {
                tone = health === "unhealthy" ? "warning" : "success";
            } else if (service.status === "Down") {
                tone = "danger";
            }

            const col = el("div", "col-sm-6 col-lg-4 col-xxl-3");
            const tile = el("div", "aat-service");
            const head = el("div", "d-flex align-items-center gap-2 min-w-0");
            head.append(el("span", `aat-dot bg-${tone}`));
            const name = el("span", "fw-semibold text-truncate", service.service);
            name.title = service.service;
            head.append(name);
            head.append(el("span", `badge rounded-pill text-bg-${tone} ms-auto`, service.status));
            tile.append(head);

            const details = [state];
            if (health && health !== "unknown") {
                details.push(health);
            }
            tile.append(el("div", "small text-body-secondary mt-1", details.join(" · ")));

            const stats = el("div", "small aat-service-stats d-flex gap-3 mt-2");
            stats.append(el("span", "", `CPU ${service.cpu || "—"}`));
            stats.append(el("span", "", `Memory ${service.memory || "—"}`));
            tile.append(stats);

            col.append(tile);
            return col;
        };

        const loadDocker = async () => {
            const list = root.querySelector("[data-docker-list]");
            const empty = root.querySelector("[data-docker-empty]");
            const summary = root.querySelector("[data-docker-summary]");
            try {
                const data = await fetchJson(root.dataset.dockerUrl);
                const services = data.services || [];
                list.replaceChildren(...services.map(serviceTile));
                if (services.length) {
                    empty.classList.add("d-none");
                    const up = services.filter((s) => s.status === "Up").length;
                    summary.textContent = `${up} of ${services.length} running`;
                } else {
                    empty.classList.remove("d-none");
                    empty.textContent = "No Docker services are configured or reachable.";
                    summary.textContent = "";
                }
            } catch (error) {
                empty.classList.remove("d-none");
                empty.textContent = "Could not load container status.";
            }
        };

        poll(loadStats, 5000);
        if (root.dataset.dockerUrl) {
            poll(loadDocker, 15000);
        }
    };

    // ------------------------------------------------------------------ operations

    const initTabs = (root) => {
        const tabs = Array.from(root.querySelectorAll("[data-aat-tab]"));
        if (!tabs.length || !window.bootstrap?.Tab) {
            return;
        }
        const key = "aa_admin_toolkit.operations.tab";
        const byName = (name) => tabs.find((tab) => tab.dataset.aatTab === name);

        tabs.forEach((tab) => {
            tab.addEventListener("shown.bs.tab", () => {
                storage.set(key, tab.dataset.aatTab);
                window.history.replaceState(null, "", `#${tab.dataset.aatTab}`);
            });
        });

        window.addEventListener("hashchange", () => {
            const tab = byName(window.location.hash.replace("#", ""));
            if (tab) {
                window.bootstrap.Tab.getOrCreateInstance(tab).show();
            }
        });

        const params = new URLSearchParams(window.location.search);
        const wanted = byName(window.location.hash.replace("#", ""))
            || (params.has("file") ? byName("files") : null)
            || byName(storage.get(key));
        if (wanted) {
            window.bootstrap.Tab.getOrCreateInstance(wanted).show();
        }
    };

    /* Shows a field group only while every "name=value value" condition holds; hidden fields are disabled. */
    const initConditionalFields = (form) => {
        const groups = Array.from(form.querySelectorAll("[data-aat-when]"));
        const rules = groups.map((group) => ({
            group,
            conditions: group.dataset.aatWhen.split(";").map((part) => {
                const [name, values] = part.split("=");
                return {name: name.trim(), values: values.trim().split(/\s+/)};
            }),
        }));

        const update = () => {
            rules.forEach(({group, conditions}) => {
                const visible = conditions.every(({name, values}) => {
                    const field = form.elements.namedItem(name);
                    return field && values.includes(field.value);
                });
                group.hidden = !visible;
                group.querySelectorAll("input, select, textarea").forEach((field) => {
                    field.disabled = !visible;
                    if (field.hasAttribute("data-aat-required")) {
                        field.required = visible;
                    }
                });
            });
        };

        form.addEventListener("change", update);
        update();
    };

    const initConfirmations = (root) => {
        const modalEl = document.getElementById("aat-confirm-modal");
        const modal = modalEl && window.bootstrap?.Modal ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;
        let pending = null;

        const messageFor = (button) => {
            const service = button.form?.elements.namedItem("service");
            return button.dataset.aatConfirm.replace("{service}", service ? service.value : "");
        };

        root.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-aat-confirm]");
            if (!button || button.disabled || button.dataset.aatConfirmed === "1") {
                return;
            }
            // Let the browser run its own field validation before asking.
            if (button.form && !button.form.checkValidity()) {
                return;
            }
            event.preventDefault();
            const message = messageFor(button);

            if (!modal) {
                if (window.confirm(message)) {
                    button.dataset.aatConfirmed = "1";
                    button.click();
                }
                return;
            }

            pending = button;
            modalEl.querySelector("[data-aat-confirm-text]").textContent = message;
            const ok = modalEl.querySelector("[data-aat-confirm-ok]");
            const danger = /warning|danger/.test(button.className);
            ok.className = `btn ${danger ? "btn-warning" : "btn-primary"}`;
            modal.show();
        });

        modalEl?.querySelector("[data-aat-confirm-ok]").addEventListener("click", () => {
            if (!pending) {
                return;
            }
            const button = pending;
            pending = null;
            button.dataset.aatConfirmed = "1";
            modal.hide();
            button.click();
        });

        modalEl?.addEventListener("hidden.bs.modal", () => {
            pending = null;
        });
    };

    /* Disables the clicked button after submit so a slow action is not queued twice. */
    const initSubmitGuard = (root) => {
        root.addEventListener("submit", (event) => {
            const form = event.target;
            if (form.method.toLowerCase() !== "post") {
                return;
            }
            const button = event.submitter;
            // Wait a tick: a disabled submitter would drop its name/value from the request.
            window.setTimeout(() => {
                form.querySelectorAll("button[type=submit]").forEach((b) => {
                    b.disabled = true;
                });
                if (button) {
                    const icon = button.querySelector("i");
                    const spinner = el("span", "spinner-border spinner-border-sm me-1");
                    spinner.setAttribute("aria-hidden", "true");
                    if (icon) {
                        icon.replaceWith(spinner);
                    } else {
                        button.prepend(spinner);
                    }
                }
            }, 0);
        });

        // Restore buttons if the page comes back from the bfcache.
        window.addEventListener("pageshow", (event) => {
            if (event.persisted) {
                window.location.reload();
            }
        });
    };

    const initOperations = (root) => {
        initTabs(root);
        root.querySelectorAll("form[data-aat-conditional]").forEach(initConditionalFields);
        root.querySelectorAll("select[data-aat-autosubmit]").forEach((select) => {
            select.addEventListener("change", () => select.form.submit());
        });
        initConfirmations(root);
        initSubmitGuard(root);
    };

    // ------------------------------------------------------------------ log detail

    const initLogPoll = (root) => {
        const url = root.dataset.aatLogPoll;
        const initialStatus = root.dataset.aatLogStatus;
        const stuck = root.querySelector("[data-aat-log-stuck]");
        const startedAt = Date.now();

        poll(async () => {
            try {
                const data = await fetchJson(url);
                if (data.status !== initialStatus || !ACTIVE_LOG_STATES.has(data.status)) {
                    window.location.reload();
                    return;
                }
                if (data.status === "PENDING" && Date.now() - startedAt > 30000) {
                    stuck?.classList.remove("d-none");
                }
            } catch (error) {
                // A failed poll is retried on the next tick.
            }
        }, 2000);
    };

    const initCopyButtons = () => {
        document.querySelectorAll("[data-aat-copy]").forEach((button) => {
            button.addEventListener("click", async () => {
                const target = document.querySelector(button.dataset.aatCopy);
                const label = button.querySelector("span");
                if (!target || !navigator.clipboard) {
                    return;
                }
                try {
                    await navigator.clipboard.writeText(target.textContent);
                    const original = label.textContent;
                    label.textContent = button.dataset.aatCopiedLabel || "Copied";
                    window.setTimeout(() => {
                        label.textContent = original;
                    }, 1500);
                } catch (error) {
                    // Clipboard access can be refused; the text is still selectable.
                }
            });
        });
    };

    const init = () => {
        document.querySelectorAll("[data-aat-dashboard]").forEach(initDashboard);
        document.querySelectorAll("[data-aat-operations]").forEach(initOperations);
        document.querySelectorAll("[data-aat-log-poll]").forEach(initLogPoll);
        initCopyButtons();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
