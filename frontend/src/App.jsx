import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const MAX_FILE_BYTES = 15 * 1024 * 1024;
let currentAccessToken = "";
const rawFetch = fetch.bind(window);

function apiFetch(input, options = {}) {
  const headers = new Headers(options.headers || {});
  if (currentAccessToken) headers.set("Authorization", "Bearer " + currentAccessToken);
  return rawFetch(input, { ...options, headers });
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

async function readApiError(response) {
  try {
    const payload = await response.json();
    return payload.detail || payload.message || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export default function App() {
  const [authStatus, setAuthStatus] = useState("checking");
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [authUser, setAuthUser] = useState(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [bootstrapName, setBootstrapName] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [teamUsers, setTeamUsers] = useState([]);
  const [newUserName, setNewUserName] = useState("");
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("lawyer");
  const [teamBusy, setTeamBusy] = useState(false);
  const [documentShares, setDocumentShares] = useState([]);
  const [shareEmail, setShareEmail] = useState("");
  const [sharePermission, setSharePermission] = useState("read");
  const [shareBusy, setShareBusy] = useState(false);
  const [sharesLoading, setSharesLoading] = useState(false);
  const [busyShareRevoke, setBusyShareRevoke] = useState("");
  const [caseShares, setCaseShares] = useState([]);
  const [caseShareEmail, setCaseShareEmail] = useState("");
  const [caseSharePermission, setCaseSharePermission] = useState("read");
  const [caseSharesLoading, setCaseSharesLoading] = useState(false);
  const [caseShareBusy, setCaseShareBusy] = useState(false);
  const [busyCaseShareRevoke, setBusyCaseShareRevoke] = useState("");
  const [documents, setDocuments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyDelete, setBusyDelete] = useState("");
  const [busyIndex, setBusyIndex] = useState("");
  const [semanticQuery, setSemanticQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchMessage, setSearchMessage] = useState("");
  const [searching, setSearching] = useState(false);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatSources, setChatSources] = useState([]);
  const [chatting, setChatting] = useState(false);
  const [cases, setCases] = useState([]);
  const [deadlines, setDeadlines] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [summary, setSummary] = useState({ active_cases: 0, documents: 0, upcoming_deadlines: 0, overdue_deadlines: 0, unread_notifications: 0 });
  const [caseTitle, setCaseTitle] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [caseJurisdiction, setCaseJurisdiction] = useState("");
  const [savingCase, setSavingCase] = useState(false);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [deadlineTitle, setDeadlineTitle] = useState("");
  const [deadlineDate, setDeadlineDate] = useState("");
  const [deadlineSourceDocumentId, setDeadlineSourceDocumentId] = useState("");
  const [deadlineSourcePage, setDeadlineSourcePage] = useState("");
  const [deadlineConfirmed, setDeadlineConfirmed] = useState(false);
  const [savingDeadline, setSavingDeadline] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const inputRef = useRef(null);
  const selectedCase = cases.find((item) => item.id === selectedCaseId) || null;

  useEffect(() => {
    let active = true;
    rawFetch(API_BASE + "/api/auth/bootstrap/status")
      .then(async (response) => {
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      })
      .then((payload) => {
        if (active) setNeedsBootstrap(Boolean(payload.needs_bootstrap));
      })
      .catch((err) => { if (active) setAuthError("Cannot connect to the backend. " + err.message); })
      .finally(() => { if (active) setAuthStatus("ready"); });
    return () => { active = false; };
  }, []);

  async function signIn(email, password) {
    const response = await rawFetch(API_BASE + "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password }).toString(),
    });
    if (!response.ok) throw new Error(await readApiError(response));
    const payload = await response.json();
    currentAccessToken = payload.access_token;
    setAccessToken(payload.access_token);
    setAuthUser(payload.user);
    setLoading(true);
    setAuthPassword("");
    setAuthError("");
  }

  async function handleLogin(event) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try { await signIn(authEmail, authPassword); }
    catch (err) { setAuthError(err.message || "Sign in failed."); }
    finally { setAuthBusy(false); }
  }

  async function handleBootstrap(event) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await rawFetch(API_BASE + "/api/auth/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: bootstrapName, email: authEmail, password: authPassword }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setNeedsBootstrap(false);
      await signIn(authEmail, authPassword);
    } catch (err) {
      setAuthError(err.message || "Administrator setup failed.");
    } finally {
      setAuthBusy(false);
    }
  }

  function handleLogout() {
    const tokenToRevoke = currentAccessToken;
    if (tokenToRevoke) {
      rawFetch(API_BASE + "/api/auth/logout", {
        method: "POST",
        headers: { Authorization: "Bearer " + tokenToRevoke },
      }).catch(() => {});
    }
    currentAccessToken = "";
    setAccessToken("");
    setAuthUser(null);
    setDocuments([]);
    setDocumentShares([]);
    setShareEmail("");
    setSharePermission("read");
    setCaseShares([]);
    setCaseShareEmail("");
    setCaseSharePermission("read");
    setCases([]);
    setDeadlines([]);
    setNotifications([]);
    setSelected(null);
    setSelectedCaseId("");
    setSummary({ active_cases: 0, documents: 0, upcoming_deadlines: 0, overdue_deadlines: 0, unread_notifications: 0 });
    setError("");
    setNotice("");
    setChatAnswer("");
    setChatSources([]);
    setChatQuestion("");
    setSearch("");
    setSemanticQuery("");
    setSearchResults([]);
    setSearchMessage("");
    setLoading(false);
  }

  const loadDocuments = useCallback(async () => {
    try {
      const response = await apiFetch(`${API_BASE}/api/documents`);
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setDocuments(payload.items || []);
      setError("");
    } catch (err) {
      setError(`Could not connect to the API. Start FastAPI on port 8000. ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCaseData = useCallback(async () => {
    try {
      const [caseResponse, deadlineResponse, notificationResponse, summaryResponse] = await Promise.all([
        apiFetch(API_BASE + "/api/cases"),
        apiFetch(API_BASE + "/api/deadlines"),
        apiFetch(API_BASE + "/api/notifications?limit=10"),
        apiFetch(API_BASE + "/api/dashboard/summary"),
      ]);
      for (const response of [caseResponse, deadlineResponse, notificationResponse, summaryResponse]) {
        if (!response.ok) throw new Error(await readApiError(response));
      }
      const [casePayload, deadlinePayload, notificationPayload, summaryPayload] = await Promise.all([
        caseResponse.json(), deadlineResponse.json(), notificationResponse.json(), summaryResponse.json(),
      ]);
      setCases(casePayload.items || []);
      setSelectedCaseId((previous) => previous || casePayload.items?.[0]?.id || "");
      setDeadlines(deadlinePayload.items || []);
      setNotifications(notificationPayload.items || []);
      setSummary(summaryPayload);
    } catch (err) {
      setError("Could not load case tracking data. " + err.message);
    }
  }, []);

  useEffect(() => {
    if (!accessToken) return;
    loadDocuments();
    loadCaseData();
    const refresh = window.setInterval(() => { loadCaseData(); }, 30000);
    return () => window.clearInterval(refresh);
  }, [loadDocuments, loadCaseData, accessToken]);

  useEffect(() => {
    if (!accessToken) return;
    let active = true;
    const controller = new AbortController();

    async function streamNotifications() {
      while (active) {
        try {
          const response = await apiFetch(API_BASE + "/api/notifications/stream", {
            headers: { Accept: "text/event-stream" },
            signal: controller.signal,
          });
          if (response.status === 401 || response.status === 403) {
            if (active) {
              setAuthError("Your session expired. Please sign in again.");
              handleLogout();
            }
            break;
          }
          if (!response.ok) throw new Error(await readApiError(response));
          if (!response.body) throw new Error("The browser does not support streamed responses.");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (active) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() || "";
            for (const block of blocks) {
              const lines = block.split(/\r?\n/);
              const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
              const dataLine = lines.find((line) => line.startsWith("data:"));
              if (eventName === "snapshot" && dataLine) {
                const payload = JSON.parse(dataLine.slice(5).trim());
                if (active) {
                  setNotifications(payload.items || []);
                  if (payload.summary) setSummary(payload.summary);
                }
              } else if (eventName === "error" && dataLine) {
                const payload = JSON.parse(dataLine.slice(5).trim());
                if (active) {
                  setAuthError(payload.detail || "Your session expired. Please sign in again.");
                  handleLogout();
                }
                active = false;
                break;
              }
            }
            if (!active) break;
          }
          if (!active || controller.signal.aborted) break;
          await new Promise((resolve) => window.setTimeout(resolve, 3000));
        } catch (err) {
          if (!active || controller.signal.aborted) break;
          await new Promise((resolve) => window.setTimeout(resolve, 3000));
        }
      }
    }

    streamNotifications();
    return () => {
      active = false;
      controller.abort();
    };
  }, [accessToken]);

  const filteredDocuments = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return documents;
    return documents.filter((item) => item.original_filename.toLowerCase().includes(term));
  }, [documents, search]);

  const canManageCases = Boolean(authUser && ["admin", "lawyer"].includes(authUser.role));
  const canUploadDocuments = Boolean(authUser && ["admin", "lawyer", "assistant"].includes(authUser.role));
  const isAdmin = authUser?.role === "admin";

  const loadTeamUsers = useCallback(async () => {
    try {
      const response = await apiFetch(API_BASE + "/api/auth/users");
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setTeamUsers(payload.items || []);
    } catch (err) {
      setError("Could not load user accounts. " + err.message);
    }
  }, []);

  useEffect(() => {
    if (accessToken && isAdmin) loadTeamUsers();
    else setTeamUsers([]);
  }, [accessToken, isAdmin, loadTeamUsers]);

  useEffect(() => {
    let active = true;
    async function loadShares() {
      if (!accessToken || !selected?.id || selected.access_level !== "owner") {
        setDocumentShares([]);
        setSharesLoading(false);
        return;
      }
      setSharesLoading(true);
      try {
        const response = await apiFetch(`${API_BASE}/api/documents/${selected.id}/shares`);
        if (!response.ok) throw new Error(await readApiError(response));
        const payload = await response.json();
        if (active) setDocumentShares(payload.items || []);
      } catch (err) {
        if (active) setError("Could not load document access. " + err.message);
      } finally {
        if (active) setSharesLoading(false);
      }
    }
    loadShares();
    return () => { active = false; };
  }, [accessToken, selected?.id, selected?.access_level]);

  useEffect(() => {
    let active = true;
    async function loadCaseShares() {
      if (!accessToken || !selectedCase?.id || selectedCase.access_level !== "owner") {
        setCaseShares([]);
        setCaseSharesLoading(false);
        return;
      }
      setCaseSharesLoading(true);
      try {
        const response = await apiFetch(`${API_BASE}/api/cases/${selectedCase.id}/shares`);
        if (!response.ok) throw new Error(await readApiError(response));
        const payload = await response.json();
        if (active) setCaseShares(payload.items || []);
      } catch (err) {
        if (active) setError("Could not load case access. " + err.message);
      } finally {
        if (active) setCaseSharesLoading(false);
      }
    }
    loadCaseShares();
    return () => { active = false; };
  }, [accessToken, selectedCase?.id, selectedCase?.access_level]);

  async function shareDocument(event) {
    event.preventDefault();
    if (!selected?.id) return;
    setShareBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API_BASE}/api/documents/${selected.id}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: shareEmail, permission: sharePermission }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const shared = await response.json();
      setShareEmail("");
      setNotice(`Shared ${selected.original_filename} with ${shared.email} (${shared.permission} access).`);
      const listResponse = await apiFetch(`${API_BASE}/api/documents/${selected.id}/shares`);
      if (!listResponse.ok) throw new Error(await readApiError(listResponse));
      const payload = await listResponse.json();
      setDocumentShares(payload.items || []);
      await loadDocuments();
    } catch (err) {
      setError(err.message || "Could not share the document.");
    } finally {
      setShareBusy(false);
    }
  }

  async function revokeDocumentShare(item) {
    if (!selected?.id || !window.confirm(`Revoke ${item.email}'s access to this document?`)) return;
    setBusyShareRevoke(item.user_id);
    setError("");
    try {
      const response = await apiFetch(`${API_BASE}/api/documents/${selected.id}/shares/${item.user_id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setDocumentShares((previous) => previous.filter((share) => share.user_id !== item.user_id));
      setNotice(`Revoked document access for ${item.email}.`);
      await loadDocuments();
    } catch (err) {
      setError(err.message || "Could not revoke document access.");
    } finally {
      setBusyShareRevoke("");
    }
  }

  async function shareCase(event) {
    event.preventDefault();
    if (!selectedCase?.id) return;
    setCaseShareBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API_BASE}/api/cases/${selectedCase.id}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: caseShareEmail, permission: caseSharePermission }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const shared = await response.json();
      setCaseShareEmail("");
      setNotice(`Shared ${selectedCase.title} with ${shared.email} (${shared.permission} access).`);
      const listResponse = await apiFetch(`${API_BASE}/api/cases/${selectedCase.id}/shares`);
      if (!listResponse.ok) throw new Error(await readApiError(listResponse));
      const payload = await listResponse.json();
      setCaseShares(payload.items || []);
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not share the case.");
    } finally {
      setCaseShareBusy(false);
    }
  }

  async function revokeCaseShare(item) {
    if (!selectedCase?.id || !window.confirm(`Revoke ${item.email}'s access to this case and its deadlines?`)) return;
    setBusyCaseShareRevoke(item.user_id);
    setError("");
    try {
      const response = await apiFetch(`${API_BASE}/api/cases/${selectedCase.id}/shares/${item.user_id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setCaseShares((previous) => previous.filter((share) => share.user_id !== item.user_id));
      setNotice(`Revoked case access for ${item.email}.`);
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not revoke case access.");
    } finally {
      setBusyCaseShareRevoke("");
    }
  }

  async function createTeamUser(event) {
    event.preventDefault();
    setTeamBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(API_BASE + "/api/auth/users", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: newUserName, email: newUserEmail, password: newUserPassword, role: newUserRole }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setNewUserName("");
      setNewUserEmail("");
      setNewUserPassword("");
      setNotice("Created account for " + newUserEmail + ".");
      await loadTeamUsers();
    } catch (err) {
      setError(err.message || "Could not create the account.");
    } finally {
      setTeamBusy(false);
    }
  }

  async function toggleTeamUser(item) {
    try {
      const response = await apiFetch(API_BASE + "/api/auth/users/" + item.id + "/active", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !item.is_active }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      await loadTeamUsers();
    } catch (err) {
      setError(err.message || "Could not update the account.");
    }
  }

  async function createCase(event) {
    event.preventDefault();
    setSavingCase(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(API_BASE + "/api/cases", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: caseTitle,
          case_number: caseNumber.trim() || null,
          jurisdiction: caseJurisdiction.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const created = await response.json();
      setSelectedCaseId(created.id);
      setCaseTitle("");
      setCaseNumber("");
      setCaseJurisdiction("");
      setNotice("Created case: " + created.title);
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not create the case.");
    } finally {
      setSavingCase(false);
    }
  }

  async function createDeadline(event) {
    event.preventDefault();
    setSavingDeadline(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(API_BASE + "/api/deadlines", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          case_id: selectedCaseId,
          title: deadlineTitle,
          due_date: deadlineDate,
          source_document_id: deadlineSourceDocumentId || null,
          source_page: deadlineSourcePage ? Number(deadlineSourcePage) : null,
          remind_days_before: 3,
          user_confirmed: deadlineConfirmed,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const created = await response.json();
      setDeadlineTitle("");
      setDeadlineDate("");
      setDeadlineSourceDocumentId("");
      setDeadlineSourcePage("");
      setDeadlineConfirmed(false);
      setNotice("Saved confirmed deadline: " + created.title);
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not create the deadline.");
    } finally {
      setSavingDeadline(false);
    }
  }

  async function completeDeadline(item) {
    try {
      const response = await apiFetch(API_BASE + "/api/deadlines/" + item.id, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "completed" }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setNotice("Marked deadline complete: " + item.title);
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not update the deadline.");
    }
  }

  async function markNotificationRead(item) {
    try {
      const response = await apiFetch(API_BASE + "/api/notifications/" + item.id + "/read", { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Could not mark the notification as read.");
    }
  }

  async function runReminderCheck() {
    try {
      const response = await apiFetch(API_BASE + "/api/reminders/run", { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = await response.json();
      setNotice("Reminder check complete. Created " + result.notifications_created + " notification(s).");
      await loadCaseData();
    } catch (err) {
      setError(err.message || "Reminder check failed.");
    }
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setNotice("");
    if (!file.name.toLowerCase().endsWith(".pdf") || file.type && file.type !== "application/pdf") {
      setError("Choose a PDF file. Other file types are not supported yet.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("This file exceeds the 15 MB upload limit.");
      return;
    }
    const body = new FormData();
    body.append("file", file);
    setUploading(true);
    try {
      const response = await apiFetch(`${API_BASE}/api/documents`, { method: "POST", body });
      if (!response.ok) throw new Error(await readApiError(response));
      const created = await response.json();
      const extractionSummary = created.text_extracted
        ? `Extracted ${created.extracted_characters.toLocaleString()} characters from ${created.page_count} page(s).`
        : "No selectable text was found; scanned pages need optional OCR before indexing.";
      const ocrSummary = created.ocr_pages_processed
        ? ` OCR processed ${created.ocr_pages_processed} scanned page(s).`
        : "";
      setNotice(`Uploaded ${created.filename}. ${extractionSummary}${ocrSummary}`);
      await loadDocuments();
      await loadCaseData();
      const detailResponse = await apiFetch(`${API_BASE}/api/documents/${created.id}`);
      if (detailResponse.ok) setSelected(await detailResponse.json());
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
    } finally {
      setUploading(false);
    }
  }

  async function openDocument(id) {
    setError("");
    try {
      const response = await apiFetch(`${API_BASE}/api/documents/${id}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setSelected(await response.json());
    } catch (err) {
      setError(err.message);
    }
  }

  async function indexDocument(item) {
    setBusyIndex(item.id);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API_BASE}/api/documents/${item.id}/index`, { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = await response.json();
      setNotice(`Indexed ${result.filename}: ${result.chunks_indexed} searchable chunks created.`);
      await loadDocuments();
    } catch (err) {
      setError(err.message || "Indexing failed. Please try again.");
    } finally {
      setBusyIndex("");
    }
  }

  async function runSemanticSearch(event) {
    event.preventDefault();
    setSearching(true);
    setError("");
    setSearchMessage("");
    setSearchResults([]);
    try {
      const response = await apiFetch(`${API_BASE}/api/search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: semanticQuery, limit: 5 }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setSearchResults(payload.items || []);
      setSearchMessage(payload.message || (payload.count ? `Found ${payload.count} relevant passage(s).` : "No matching passages found. Index documents or try a different query."));
    } catch (err) {
      setError(err.message || "Search failed. Please try again.");
    } finally {
      setSearching(false);
    }
  }

  async function submitChat(event) {
    event.preventDefault();
    setChatting(true);
    setChatAnswer("");
    setChatSources([]);
    setError("");
    try {
      const response = await apiFetch(API_BASE + "/api/chat/stream", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: chatQuestion, limit: 5 }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const reader = response.body?.getReader();
      if (!reader) throw new Error("This browser does not support streamed responses.");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          let eventType = "message";
          const dataLines = [];
          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          const payload = JSON.parse(dataLines.join("\n"));
          if (eventType === "sources") setChatSources(payload);
          else if (eventType === "token") setChatAnswer((previous) => previous + (payload.text || ""));
          else if (eventType === "error") throw new Error(payload.detail || "The AI stream failed.");
        }
        if (done) break;
      }
    } catch (err) {
      setError(err.message || "The AI chat request failed.");
    } finally {
      setChatting(false);
    }
  }

  async function removeDocument(item) {
    if (!window.confirm(`Delete "${item.original_filename}" and its extracted text? This cannot be undone.`)) return;
    setBusyDelete(item.id);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API_BASE}/api/documents/${item.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      if (selected?.id === item.id) setSelected(null);
      setNotice(`Deleted ${item.original_filename}.`);
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyDelete("");
    }
  }

  if (authStatus === "checking") {
    return <main className="auth-shell"><div className="auth-card"><span className="brand-mark">L</span><h1>Legal AI <em>Intelligence</em></h1><p>Preparing your secure workspace…</p></div></main>;
  }

  if (!accessToken || !authUser) {
    return (
      <main className="auth-shell">
        <div className="auth-card">
          <span className="brand-mark">L</span>
          <p className="eyebrow">{needsBootstrap ? "INITIAL SECURE SETUP" : "SECURE WORKSPACE"}</p>
          <h1>{needsBootstrap ? <>Create your <em>administrator</em></> : <>Welcome <em>back.</em></>}</h1>
          <p className="auth-intro">{needsBootstrap ? "Create the first administrator account. This one-time setup closes after the account is created." : "Sign in to access your case files, legal document search, and deadline tracker."}</p>
          {authError && <div className="message message-error" role="alert"><span>!</span><p>{authError}</p></div>}
          <form className="auth-form" onSubmit={needsBootstrap ? handleBootstrap : handleLogin}>
            {needsBootstrap && <label>Full name<input value={bootstrapName} onChange={(event) => setBootstrapName(event.target.value)} required minLength={2} maxLength={120} autoComplete="name" placeholder="Your name" /></label>}
            <label>Email address<input type="email" value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} required maxLength={254} autoComplete="username" placeholder="you@example.com" /></label>
            <label>Password<input type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} required minLength={needsBootstrap ? 12 : 1} maxLength={256} autoComplete={needsBootstrap ? "new-password" : "current-password"} placeholder={needsBootstrap ? "At least 12 characters" : "Your password"} /></label>
            <button className="button-primary" type="submit" disabled={authBusy}>{authBusy ? "Please wait…" : needsBootstrap ? "Create administrator ↗" : "Sign in securely ↗"}</button>
          </form>
          <p className="auth-footnote">Access tokens stay in memory and are cleared when you sign out. Do not use this local development app for confidential client files until production security review and operational safeguards are complete.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Legal AI Assistant home">
          <span className="brand-mark">L</span>
          <span>Legal AI <span className="brand-light">/ Intelligence</span></span>
        </a>
        <div className="topbar-right"><span className="api-status"><span className={error && documents.length === 0 ? "status-dot status-error" : "status-dot"} />{error && documents.length === 0 ? "API connection needed" : "Local workspace"}</span><span className="user-role">{authUser.full_name} · {authUser.role}</span><button className="logout-button" onClick={handleLogout}>Sign out</button><span className="phase-label">CASE + DOCUMENTS</span></div>
      </header>

      <section className="hero">
        <p className="eyebrow">LEGAL RESEARCH · CASE INTELLIGENCE · COMPLIANCE</p>
        <h1>Evidence first.<br /><em>Answers you can verify.</em></h1>
        <p className="hero-copy">Bring your case documents into one workspace. Upload a PDF, extract its text, and inspect the source before moving on to search and AI-assisted research.</p>
        <div className="hero-foot"><span className="hero-index">01 / CASE & DOCUMENT INTELLIGENCE</span><span className="disclaimer">Research support only · Not legal advice</span></div>
      </section>

      <section className="case-dashboard" id="cases">
        <div className="section-heading"><div><p className="eyebrow">CASE OPERATIONS</p><h2>Case tracker</h2></div>{isAdmin && <button className="button-secondary reminder-button" onClick={runReminderCheck}>Check reminders now ↻</button>}</div>
        <div className="summary-grid">
          <article><span>ACTIVE CASES</span><strong>{summary.active_cases}</strong></article>
          <article><span>DOCUMENTS</span><strong>{summary.documents}</strong></article>
          <article><span>DUE IN 7 DAYS</span><strong>{summary.upcoming_deadlines}</strong></article>
          <article className={summary.overdue_deadlines ? "summary-alert" : ""}><span>OVERDUE</span><strong>{summary.overdue_deadlines}</strong></article>
          <article><span>UNREAD ALERTS</span><strong>{summary.unread_notifications}</strong></article>
        </div>

        <div className="management-grid">
          <section className="management-card">
            <div className="management-title"><p className="eyebrow">CASE REGISTER</p><h3>Create a case</h3></div>
            <form className="stacked-form" onSubmit={createCase}>
              <label>Case title<input value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} required minLength={3} maxLength={180} placeholder="e.g. Supplier contract dispute" /></label>
              <div className="form-row"><label>Case number <span>(optional)</span><input value={caseNumber} onChange={(event) => setCaseNumber(event.target.value)} maxLength={120} placeholder="Case / reference ID" /></label><label>Jurisdiction <span>(optional)</span><input value={caseJurisdiction} onChange={(event) => setCaseJurisdiction(event.target.value)} maxLength={120} placeholder="Court or region" /></label></div>
              <button className="button-primary" type="submit" disabled={savingCase || !canManageCases}>{savingCase ? "Saving…" : "Create case +"}</button>
            </form>
            <div className="case-list"><h4>Saved cases <span>{cases.length}</span></h4>
              {cases.length === 0 ? <p className="subtle-copy">No cases yet. Create one to attach deadlines.</p> : cases.map((item) => <button className={"case-list-item " + (selectedCaseId === item.id ? "case-selected" : "")} key={item.id} onClick={() => setSelectedCaseId(item.id)}>
                <span><strong>{item.title}</strong><small>{item.case_number || item.jurisdiction || "No reference added"}{item.access_level !== "owner" ? " · Shared " + item.access_level : ""}</small></span><span className={"status-pill status-" + item.status}>{item.status}</span>
              </button>)}
            </div>
            {selectedCase?.access_level === "owner" && <section className="share-panel case-share-panel" aria-label="Case sharing controls">
              <div className="share-panel-heading"><div><p className="eyebrow">CONTROLLED ACCESS</p><h4>Share this case</h4><p>Collaborators can access this case and its deadlines.</p></div><span className="share-lock">OWNER ONLY</span></div>
              <form className="share-form" onSubmit={shareCase}>
                <label>Account email<input type="email" value={caseShareEmail} onChange={(event) => setCaseShareEmail(event.target.value)} required maxLength={254} placeholder="colleague@example.com" /></label>
                <label>Permission<select value={caseSharePermission} onChange={(event) => setCaseSharePermission(event.target.value)}><option value="read">Read only</option><option value="write">Can edit</option></select></label>
                <button className="button-primary" type="submit" disabled={caseShareBusy || !caseShareEmail.trim()}>{caseShareBusy ? "Sharing…" : "Grant access +"}</button>
              </form>
              <div className="share-list"><h5>People with access <span>{caseShares.length}</span></h5>
                {caseSharesLoading ? <p className="subtle-copy">Loading access list…</p> : caseShares.length === 0 ? <p className="subtle-copy">This case is private to your account.</p> : caseShares.map((item) => <article className="share-row" key={item.user_id}>
                  <div><strong>{item.full_name}</strong><small>{item.email}</small></div>
                  <div className="share-row-actions"><span className="status-pill">{item.permission} access</span><button className="read-button" type="button" disabled={busyCaseShareRevoke === item.user_id} onClick={() => revokeCaseShare(item)}>{busyCaseShareRevoke === item.user_id ? "Revoking…" : "Revoke"}</button></div>
                </article>)}
              </div>
              <p className="share-note">Revoking access immediately hides this case, its deadlines, and its case notifications from the collaborator.</p>
            </section>}
          </section>

          <section className="management-card">
            <div className="management-title"><p className="eyebrow">VERIFIED OBLIGATIONS</p><h3>Record a deadline</h3><p>Only save dates you have verified from a reliable source.</p></div>
            {cases.length === 0 ? <p className="subtle-copy">Create a case first, then you can add its deadlines.</p> : <form className="stacked-form" onSubmit={createDeadline}>
              <label>Case<select value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)} required>{cases.filter((item) => item.status === "active").map((item) => <option value={item.id} key={item.id} disabled={item.access_level === "read"}>{item.title}{item.access_level === "read" ? " (read only)" : ""}</option>)}</select></label>
              <label>Deadline / action<input value={deadlineTitle} onChange={(event) => setDeadlineTitle(event.target.value)} required minLength={3} maxLength={180} placeholder="e.g. File written response" /></label>
              <label>Due date<input type="date" value={deadlineDate} onChange={(event) => setDeadlineDate(event.target.value)} required /></label>
              <label>Source document <span>(optional)</span><select value={deadlineSourceDocumentId} onChange={(event) => { setDeadlineSourceDocumentId(event.target.value); setDeadlineSourcePage(""); }}><option value="">No document linked</option>{documents.map((item) => <option value={item.id} key={item.id}>{item.original_filename}</option>)}</select></label>
              {deadlineSourceDocumentId && <label>Source page<input type="number" min="1" max={documents.find((item) => item.id === deadlineSourceDocumentId)?.page_count || 500} value={deadlineSourcePage} onChange={(event) => setDeadlineSourcePage(event.target.value)} required placeholder="Page containing the date" /></label>}
              <label className="confirm-check"><input type="checkbox" checked={deadlineConfirmed} onChange={(event) => setDeadlineConfirmed(event.target.checked)} required /><span>I have verified this date and action against the source or an authoritative record.</span></label>
              <button className="button-primary" type="submit" disabled={savingDeadline || !selectedCaseId || !deadlineConfirmed || !canManageCases || selectedCase?.access_level === "read"}>{savingDeadline ? "Saving…" : "Save confirmed deadline +"}</button>
            </form>}
          </section>
        </div>

        <div className="operations-grid">
          <section className="management-card">
            <div className="management-title"><p className="eyebrow">CALENDAR WATCH</p><h3>Deadlines</h3></div>
            {deadlines.length === 0 ? <p className="subtle-copy">No deadlines recorded yet.</p> : <div className="deadline-list">{deadlines.map((item) => <article className="deadline-item" key={item.id}>
              <div className="deadline-date"><strong>{new Date(item.due_date + "T12:00:00").toLocaleDateString(undefined, { day: "2-digit" })}</strong><span>{new Date(item.due_date + "T12:00:00").toLocaleDateString(undefined, { month: "short" })}</span></div>
              <div className="deadline-info"><strong>{item.title}</strong><small>{item.case_title} · Due {item.due_date}{item.source_page ? " · Source p. " + item.source_page : ""}</small></div>
              {item.status === "pending" && canManageCases && item.access_level !== "read" ? <button className="complete-button" onClick={() => completeDeadline(item)}>Complete</button> : <span className={"status-pill status-" + item.status}>{item.status}</span>}
            </article>)}</div>}
          </section>
          <section className="management-card">
            <div className="management-title notification-title"><div><p className="eyebrow">REMINDER FEED</p><h3>Notifications</h3></div><span className="notification-count">{notifications.filter((item) => !item.read_at).length} unread</span></div>
            {notifications.length === 0 ? <p className="subtle-copy">No notifications. A reminder check runs automatically in the background.</p> : <div className="notification-list">{notifications.map((item) => <article className={"notification-item " + (!item.read_at ? "notification-unread" : "")} key={item.id}>
              <span className={"notification-symbol " + (item.notification_type === "deadline_overdue" ? "symbol-alert" : "")}>{item.notification_type === "deadline_overdue" ? "!" : "↗"}</span>
              <div><strong>{item.title}</strong><p>{item.body}</p><small>{formatDate(item.created_at)}{item.case_title ? " · " + item.case_title : ""}</small></div>
              {!item.read_at && <button className="read-button" onClick={() => markNotificationRead(item)}>Mark read</button>}
            </article>)}</div>}
          </section>
        </div>
      </section>

      {isAdmin && <section className="team-panel" id="team">
        <div className="section-heading"><div><p className="eyebrow">ACCESS CONTROL</p><h2>Team accounts</h2></div><span className="team-count">{teamUsers.length} account(s)</span></div>
        <div className="team-grid">
          <section className="management-card">
            <div className="management-title"><h3>Create an account</h3><p>Passwords require at least 12 characters.</p></div>
            <form className="stacked-form" onSubmit={createTeamUser}>
              <label>Full name<input value={newUserName} onChange={(event) => setNewUserName(event.target.value)} required minLength={2} maxLength={120} /></label>
              <label>Email address<input type="email" value={newUserEmail} onChange={(event) => setNewUserEmail(event.target.value)} required maxLength={254} /></label>
              <label>Temporary password<input type="password" value={newUserPassword} onChange={(event) => setNewUserPassword(event.target.value)} required minLength={12} maxLength={256} autoComplete="new-password" /></label>
              <label>Role<select value={newUserRole} onChange={(event) => setNewUserRole(event.target.value)}><option value="lawyer">Lawyer</option><option value="assistant">Assistant</option><option value="viewer">Viewer (read only)</option><option value="admin">Administrator</option></select></label>
              <button className="button-primary" type="submit" disabled={teamBusy}>{teamBusy ? "Creating…" : "Create account +"}</button>
            </form>
          </section>
          <section className="management-card">
            <div className="management-title"><h3>Account permissions</h3><p>Disabled accounts lose access on their next request.</p></div>
            <div className="team-user-list">{teamUsers.map((item) => <article className="team-user" key={item.id}>
              <div><strong>{item.full_name}</strong><small>{item.email}</small><span className={"status-pill status-" + (item.is_active ? "active" : "archived")}>{item.role} · {item.is_active ? "active" : "disabled"}</span></div>
              <button className="read-button" disabled={item.id === authUser.id} onClick={() => toggleTeamUser(item)}>{item.is_active ? "Disable" : "Enable"}</button>
            </article>)}</div>
          </section>
        </div>
      </section>}

      <section className="workspace" id="workspace">
        <div className="section-heading">
          <div><p className="eyebrow">YOUR CASE FILES</p><h2>Document library</h2></div>
          <div className="document-count"><strong>{documents.length.toString().padStart(2, "0")}</strong><span>documents</span></div>
        </div>

        <div className="upload-panel">
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15.5v3A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg></div>
          <div className="upload-copy"><h3>Upload a legal document</h3><p>PDF only · Up to 15 MB · Text extraction runs locally through the API</p></div>
          <input ref={inputRef} className="visually-hidden" type="file" accept="application/pdf,.pdf" onChange={handleUpload} />
          <button className="button-primary" type="button" disabled={uploading || !canUploadDocuments} onClick={() => inputRef.current?.click()}>{uploading ? <><span className="spinner" /> Processing…</> : "Choose PDF ↗"}</button>
        </div>

        {error && <div className="message message-error" role="alert"><span>!</span><div><strong>Something needs attention</strong><p>{error}</p></div><button className="message-close" onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
        {notice && <div className="message message-success" role="status"><span>✓</span><p>{notice}</p><button className="message-close" onClick={() => setNotice("")} aria-label="Dismiss notice">×</button></div>}

        <section className="semantic-panel">
          <div className="semantic-heading"><div><p className="eyebrow">RETRIEVAL WORKSPACE</p><h3>Search across your documents</h3><p>Ask a question in natural language to find related passages and page references.</p></div><span className="semantic-mark">⌕</span></div>
          <form className="semantic-form" onSubmit={runSemanticSearch}>
            <input value={semanticQuery} onChange={(event) => setSemanticQuery(event.target.value)} minLength={3} maxLength={1000} required placeholder="e.g. What does the contract say about termination notice?" aria-label="Semantic search query" />
            <button className="button-primary" type="submit" disabled={searching || semanticQuery.trim().length < 3}>{searching ? <><span className="spinner" /> Searching…</> : "Find passages ↗"}</button>
          </form>
          {searchMessage && <p className="search-message" role="status">{searchMessage}</p>}
          {searchResults.length > 0 && <div className="search-results">{searchResults.map((result) => <article className="search-result" key={result.document_id + "-" + result.chunk_index}>
            <div className="result-meta"><button onClick={() => openDocument(result.document_id)}>{result.filename}</button><span>Page {result.page_start}{result.page_end !== result.page_start ? "–" + result.page_end : ""}</span><span>Cosine {result.score.toFixed(2)}</span></div>
            <p>{result.text}</p>
          </article>)}</div>}
        </section>

        <section className="chat-panel">
          <div className="chat-heading"><div><p className="eyebrow">DOCUMENT-GROUNDED AI</p><h3>Ask your legal documents</h3><p>Answers use retrieved passages, with source labels and page references. No source, no assumed fact.</p></div><span className="chat-mark">✳</span></div>
          <form className="chat-form" onSubmit={submitChat}>
            <textarea value={chatQuestion} onChange={(event) => setChatQuestion(event.target.value)} minLength={3} maxLength={2000} required rows={3} placeholder="Ask a question about the documents you have indexed…" aria-label="Question for the legal document assistant" />
            <div className="chat-form-footer"><span>Verify legal conclusions and dates against the cited source.</span><button className="button-primary" type="submit" disabled={chatting || chatQuestion.trim().length < 3}>{chatting ? <><span className="spinner" /> Researching…</> : "Ask documents ↗"}</button></div>
          </form>
          {chatAnswer && <div className="chat-answer"><p className="answer-label">AI RESEARCH RESPONSE</p><div className="answer-text">{chatAnswer}</div>
            {chatSources.length > 0 && <div className="chat-sources"><h4>Retrieved sources</h4>{chatSources.map((source) => <article className="chat-source" key={source.source_id}>
              <div><span className="source-id">{source.source_id}</span><button onClick={() => openDocument(source.document_id)}>{source.filename}</button><span className="source-pages">Page {source.page_start}{source.page_end !== source.page_start ? "–" + source.page_end : ""}</span></div>
              <p>{source.excerpt}</p>
            </article>)}</div>}
            <p className="chat-disclaimer">AI-generated research assistance, not legal advice. Check every cited passage in context.</p>
          </div>}
        </section>

        <div className="library-toolbar">
          <div><h3>Stored documents</h3><p>Files are saved to the configured local data directory.</p></div>
          <label className="search-box"><svg viewBox="0 0 24 24" fill="none"><circle cx="10.8" cy="10.8" r="6.8" stroke="currentColor" strokeWidth="1.5"/><path d="m16 16 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search filenames" aria-label="Search filenames" /></label>
        </div>

        {loading ? <div className="empty-state"><span className="spinner spinner-dark" /><p>Loading your document library…</p></div> : filteredDocuments.length === 0 ? (
          <div className="empty-state"><div className="empty-file">PDF</div><h3>{search ? "No matching documents" : "Your document library is ready"}</h3><p>{search ? "Try another filename." : "Upload your first PDF to extract text and see it appear here."}</p><button className="button-secondary" onClick={() => inputRef.current?.click()} disabled={uploading || !canUploadDocuments}>Upload a PDF</button></div>
        ) : (
          <div className="document-table-wrap"><table className="document-table"><thead><tr><th>DOCUMENT</th><th>PAGES</th><th>SIZE</th><th>ADDED</th><th><span className="visually-hidden">Actions</span></th></tr></thead><tbody>
            {filteredDocuments.map((item) => <tr key={item.id} className={selected?.id === item.id ? "selected-row" : ""}>
              <td><button className="document-name" onClick={() => openDocument(item.id)}><span className="pdf-badge">PDF</span><span><strong>{item.original_filename}</strong><small>{Number(item.extracted_characters || 0).toLocaleString()} extracted characters</small>{item.access_level !== "owner" && <small className="shared-label">Shared with you · {item.access_level === "write" ? "can index" : "read only"}</small>}</span></button></td>
              <td>{item.page_count}</td><td>{formatBytes(item.size_bytes)}</td><td className="date-cell">{formatDate(item.created_at)}</td>
              <td className="row-actions"><button className="index-button" onClick={() => indexDocument(item)} disabled={busyIndex === item.id || !canUploadDocuments || item.access_level === "read"}>{busyIndex === item.id ? "Indexing…" : item.indexed ? "Re-index" : "Index"}</button>{item.access_level === "owner" && <button className="share-button" type="button" onClick={() => openDocument(item.id)}>Share</button>}<button className="delete-button" onClick={() => removeDocument(item)} disabled={busyDelete === item.id || !canManageCases || item.access_level !== "owner"} aria-label={`Delete ${item.original_filename}`}>{busyDelete === item.id ? "…" : "Delete"}</button></td>
            </tr>)}
          </tbody></table></div>
        )}

        {selected && <section className="detail-panel" aria-label="Document extracted text">
          <div className="detail-heading"><div><p className="eyebrow">SOURCE PREVIEW</p><h3>{selected.original_filename}</h3><p>{selected.page_count} page(s) · SHA-256 <code>{selected.sha256}</code></p></div><button className="close-detail" onClick={() => setSelected(null)} aria-label="Close document preview">×</button></div>
          {selected.access_level === "owner" && <section className="share-panel" aria-label="Document sharing controls">
            <div className="share-panel-heading"><div><p className="eyebrow">DOCUMENT ACCESS</p><h4>Share this document</h4><p>Grant access to an active account using its email address.</p></div><span className="share-lock">OWNER</span></div>
            <form className="share-form" onSubmit={shareDocument}>
              <label>Account email<input type="email" value={shareEmail} onChange={(event) => setShareEmail(event.target.value)} required maxLength={254} placeholder="colleague@example.com" /></label>
              <label>Permission<select value={sharePermission} onChange={(event) => setSharePermission(event.target.value)}><option value="read">Read only</option><option value="write">Can index</option></select></label>
              <button className="button-primary" type="submit" disabled={shareBusy || !shareEmail.trim()}>{shareBusy ? "Sharing…" : "Grant access +"}</button>
            </form>
            <div className="share-list">
              <h5>People with access <span>{documentShares.length}</span></h5>
              {sharesLoading ? <p className="subtle-copy">Loading access list…</p> : documentShares.length === 0 ? <p className="subtle-copy">This document is private to your account.</p> : documentShares.map((item) => <article className="share-row" key={item.user_id}>
                <div><strong>{item.full_name}</strong><small>{item.email}</small></div>
                <div className="share-row-actions"><span className={"status-pill " + (item.permission === "write" ? "status-active" : "status-archived")}>{item.permission === "write" ? "Can index" : "Read only"}</span><button className="read-button" type="button" onClick={() => revokeDocumentShare(item)} disabled={busyShareRevoke === item.user_id}>{busyShareRevoke === item.user_id ? "Revoking…" : "Revoke"}</button></div>
              </article>)}
            </div>
            <p className="share-note">Read-only users can preview and search this document. “Can index” also permits indexing; only the owner can delete the file or change sharing.</p>
          </section>}
          <div className="extracted-text">{selected.extracted_text ? selected.extracted_text : "No selectable text was found in this PDF. It may be a scanned document; OCR support has not been added yet."}</div>
        </section>}
      </section>

      <footer className="footer"><span>LEGAL AI ASSISTANT</span><span>Case sharing is available; production security review and operational hardening are still required.</span></footer>
    </main>
  );
}