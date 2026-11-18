const API = "/api";
const state = {
  member: null,
  books: [],
  featuredIndex: 0,
  reservations: [],
  loans: [],
  pendingBook: null
};

const $ = (selector) => document.querySelector(selector);
const featuredCatalog = [
  { title:"The City of Moon", author:"Mara Bell", subject:"Fiction", description:"A cartographer’s daughter follows vanished streets through a city that remakes itself after midnight.", art:"art-night", cover:"THE CITY OF MOON", style:"cover-red" },
  { title:"A Field Atlas", author:"Inez Rao", subject:"Science", description:"A visual survey of hidden ecologies, from tidal pools to mountain light.", art:"art-green", cover:"FIELD ATLAS", style:"cover-sage" },
  { title:"The Blue Archive", author:"Samir Wells", subject:"History", description:"Letters, maps, and fragments reconstruct a century erased from the official record.", art:"art-blue", cover:"THE BLUE ARCHIVE", style:"cover-blue" }
];

function initials(name) {
  return name.trim().split(/\s+/).slice(0,2).map(part => part[0]).join("").toUpperCase();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => toast.classList.remove("visible"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { "Content-Type":"application/json", ...(options.headers || {}) }
  });
  if (!response.ok) {
    let detail = "The service could not complete this request.";
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

$("#togglePassword").addEventListener("click", () => {
  const field = $("#loginPassword");
  const isHidden = field.type === "password";
  field.type = isHidden ? "text" : "password";
  $("#togglePassword").textContent = isHidden ? "Hide" : "Show";
});

async function signIn(name, email) {
  const members = await api("/member/members?limit=100&offset=0");
  let member = (members.items || []).find(item => item.email.toLowerCase() === email.toLowerCase()) || null;
  if (!member) {
    member = await api("/member/members", { method:"POST", body:JSON.stringify({name,email}) });
  }

  state.member = member;
  localStorage.setItem("bibliothecaMember", JSON.stringify(member));
  $("#loginScreen").hidden = true;
  $("#appShell").hidden = false;
  $("#memberInitials").textContent = initials(member.name);
  $("#accountMonogram").textContent = initials(member.name);
  $("#accountName").textContent = member.name;
  $("#accountEmail").textContent = member.email;
  await loadCatalog();
  await refreshMemberData();
  showToast(`Welcome, ${member.name.split(" ")[0]}`);
}

$("#loginForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await signIn($("#loginName").value, $("#loginEmail").value);
  } catch (error) { showToast(error.message); }
});
$("#demoLogin").addEventListener("click", () => signIn("Nishant Pradhan", "nishant@example.com").catch(error => showToast(error.message)));

$("#signOutButton").addEventListener("click", () => {
  localStorage.removeItem("bibliothecaMember");
  state.member = null;
  $("#loginName").value = "Nishant Pradhan";
  $("#loginEmail").value = "nishant@example.com";
  $("#loginPassword").value = "library123";
  $("#appShell").hidden = true;
  $("#loginScreen").hidden = false;
});

$("#accountButton").addEventListener("click", () => switchView("account"));

async function loadCatalog() {
  const page = await api("/catalog/books?limit=100");
  state.books = page.items || [];
  renderBooks(state.books);
  showFeature(state.featuredIndex);
}

function bookMeta(book, index) {
  const art = index % 4;
  const style = ["cover-red","cover-sage","cover-blue","cover-gold"][art];
  const name = book.title.toUpperCase().replace(/\s+/g,"<br>");
  return { style, name };
}

function renderBooks(items) {
  if (!items.length) {
    $("#bookGrid").innerHTML = `<div class="empty-state"><h2>No titles found</h2><p>Try another title or subject.</p></div>`;
    return;
  }
  $("#bookGrid").innerHTML = items.map((book,index) => {
    const meta = bookMeta(book,index);
    return `<article class="book-card">
      <div class="cover ${meta.style}"><span class="cover-seal"></span><div class="cover-name">${meta.name}</div></div>
      <h3>${escapeHtml(book.title)}</h3>
      <p class="author">${escapeHtml(book.author)}</p>
      <div class="book-card-footer"><span id="availability-${book.book_id}">Checking copies</span><button type="button" data-reserve="${book.book_id}" data-title="${escapeHtml(book.title)}">Reserve</button></div>
    </article>`;
  }).join("");
  items.forEach(async book => {
    const node = $(`#availability-${CSS.escape(book.book_id)}`);
    if (!node) return;
    try {
      const availability = await api(`/availability/books/${book.book_id}/availability`);
      node.textContent = `${availability.available_copies} ${availability.available_copies === 1 ? "copy" : "copies"} available`;
    } catch { node.textContent = "Check availability"; }
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[char]));
}

function showFeature(index) {
  if (!state.books.length) return;
  state.featuredIndex = (index + state.books.length) % state.books.length;
  const book = state.books[state.featuredIndex];
  const art = document.querySelector(".book-art");
  const artClasses = ["art-night","art-green","art-blue","art-red","art-gold"];
  art.className = `book-art ${artClasses[state.featuredIndex % artClasses.length]}`;
  art.querySelector(".art-title").innerHTML = book.title.toUpperCase().replace(/\s+/g,"<br>");
  $("#featuredTitle").textContent = book.title;
  $("#featuredAuthor").textContent = book.author;
  $("#featuredDescription").textContent = featuredCatalog[state.featuredIndex]?.description || "A new addition to the Bibliotheca collection.";
  $("#featuredReserve").dataset.reserve = book.book_id;
  $("#featuredReserve").dataset.title = book.title;
  api(`/availability/books/${book.book_id}/availability`)
    .then(availability => {
      $("#featuredAvailability").textContent = `${availability.available_copies} ${availability.available_copies === 1 ? "copy" : "copies"} available`;
    })
    .catch(() => { $("#featuredAvailability").textContent = "Availability unavailable"; });
  $("#featureIndex").textContent = String(state.featuredIndex + 1).padStart(2,"0");
}

$("#previousFeature").addEventListener("click", () => showFeature(state.featuredIndex - 1));
$("#nextFeature").addEventListener("click", () => showFeature(state.featuredIndex + 1));

$("#searchForm").addEventListener("submit", event => {
  event.preventDefault();
  applySearch($("#searchInput").value);
});
document.querySelectorAll("[data-search]").forEach(button => button.addEventListener("click", () => {
  $("#searchInput").value = button.dataset.search;
  applySearch(button.dataset.search);
}));
$("#viewAll").addEventListener("click", () => {
  $("#searchInput").value = "";
  $("#collectionTitle").textContent = "Today’s reading";
  renderBooks(state.books);
});

function applySearch(query) {
  const normalized = query.trim().toLowerCase();
  const matches = state.books.filter(book => {
    const featured = featuredCatalog.find(item => item.title === book.title);
    return [book.title, book.author, book.isbn || "", featured?.subject || ""].join(" ").toLowerCase().includes(normalized);
  });
  $("#collectionTitle").textContent = normalized ? `Results for “${query.trim()}”` : "Today’s reading";
  renderBooks(matches);
  $("#collectionSection").scrollIntoView({behavior:"smooth"});
  showToast(matches.length ? `${matches.length} title${matches.length === 1 ? "" : "s"} found` : "No titles found");
}

document.addEventListener("click", event => {
  const reserveButton = event.target.closest("[data-reserve]");
  if (reserveButton) openReservation(reserveButton.dataset.reserve, reserveButton.dataset.title);
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) switchView(viewButton.dataset.view);
});

async function openReservation(bookId, title) {
  if (!state.member) return;
  state.pendingBook = state.books.find(book => book.book_id === bookId) || {book_id:bookId,title};
  $("#dialogTitle").textContent = `Reserve “${title}”`;
  $("#holdSummary").innerHTML = `<span>${escapeHtml(title)}</span><span>Ready hold</span>`;
  $("#reserveDialog").showModal();
}
$("#closeReserve").addEventListener("click", () => $("#reserveDialog").close());

$("#reserveForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const response = await api("/reservations/reservations", { method:"POST", body:JSON.stringify({book_id:state.pendingBook.book_id,member_id:state.member.member_id}) });
    $("#reserveDialog").close();
    showToast(`Reservation placed for “${state.pendingBook.title}”`);
    await refreshMemberData();
  } catch (error) {
    $("#reserveDialog").close();
    showToast(error.message);
  }
});

function switchView(view) {
  $("#discoverView").hidden = view !== "discover";
  $("#collectionSection").hidden = view !== "discover";
  document.querySelectorAll("[data-page]").forEach(section => section.hidden = section.dataset.page !== view);
  document.querySelectorAll(".nav-link").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  if (view === "loans") refreshLoans();
  if (view === "reservations") refreshReservations();
  if (view === "account") $("#accountView").hidden = false;
  window.scrollTo({top:0,behavior:"smooth"});
}

async function refreshMemberData() {
  await Promise.all([refreshReservations(false), refreshLoans(false)]);
}

async function refreshReservations(render = true) {
  if (!state.member) {
    state.reservations = [];
    if (render) renderReservations();
    return;
  }
  const data = await api(`/reservations/reservations?member_id=${state.member.member_id}&limit=100&offset=0`);
  state.reservations = data.items || [];
  if (render) renderReservations();
}

async function refreshLoans(render = true) {
  if (!state.member) return;
  const data = await api(`/loans/loans?member_id=${state.member.member_id}&limit=100&offset=0`);
  state.loans = data.items || [];
  if (render) renderLoans();
}

function renderReservations() {
  const list = $("#reservationList");
  if (!state.reservations.length) {
    list.innerHTML = `<div class="empty-state"><h2>No reservations yet</h2><p>Choose a title from the collection to place a hold.</p></div>`;
    return;
  }
  list.innerHTML = state.reservations.map(reservation => {
    const book = state.books.find(item => item.book_id === reservation.book_id);
    return `<article class="record-card">
      <div class="record-cover">${escapeHtml((book?.title || "Library").split(" ").slice(0,2).join("<br>"))}</div>
      <div><h3>${escapeHtml(book?.title || "Library title")}</h3><p>${escapeHtml(book?.author || "Bibliotheca")}</p></div>
      <div><span class="record-status ${reservation.status === "WAITLISTED" ? "waitlist" : ""}">${reservation.status}</span></div>
      <div><p>Hold #${reservation.queue_position}</p></div>
      <div class="record-actions">
        ${reservation.status === "READY" ? `<button type="button" data-borrow-reservation="${reservation.reservation_id}" data-book-id="${reservation.book_id}">Borrow</button>` : ""}
        <button type="button" data-cancel-reservation="${reservation.reservation_id}">Cancel hold</button>
      </div>
    </article>`;
  }).join("");
}

function renderLoans() {
  const active = state.loans.filter(loan => loan.status === "ACTIVE");
  const returned = state.loans.filter(loan => loan.status === "RETURNED");
  $("#loanStats").innerHTML = `<div class="stat"><strong>${active.length}</strong><span>Active loans</span></div><div class="stat"><strong>${returned.length}</strong><span>Returned</span></div><div class="stat"><strong>${state.reservations.length}</strong><span>Reservations</span></div>`;
  const list = $("#loanList");
  if (!state.loans.length) {
    list.innerHTML = `<div class="empty-state"><h2>No loans on your card</h2><p>Place a reservation, then use it to borrow a copy.</p></div>`;
    return;
  }
  list.innerHTML = state.loans.map(loan => {
    const book = state.books.find(item => item.book_id === loan.book_id);
    return `<article class="record-card">
      <div class="record-cover">${escapeHtml((book?.title || "Loan").split(" ").slice(0,2).join("<br>"))}</div>
      <div><h3>${escapeHtml(book?.title || "Library loan")}</h3><p>${escapeHtml(book?.author || "")}</p></div>
      <div><span class="record-status">${loan.status}</span></div>
      <div><p>Due ${new Date(loan.due_at).toLocaleDateString()}</p></div>
      ${loan.status === "ACTIVE" ? `<button type="button" data-return-loan="${loan.loan_id}">Return</button>` : `<button type="button" disabled>Returned</button>`}
    </article>`;
  }).join("");
}

document.addEventListener("click", async event => {
  const borrow = event.target.closest("[data-borrow-reservation]");
  if (borrow) {
    try {
      const copies = await api(`/catalog/books/${borrow.dataset.bookId}/copies?limit=100`);
      const copy = copies.items?.find(item => item.copy_id === state.reservations.find(
        reservation => reservation.reservation_id === borrow.dataset.borrowReservation
      )?.copy_id);
      if (!copy) throw new Error("No available copy for this title");
      await api("/loans/loans", {
        method:"POST",
        body:JSON.stringify({
          member_id:state.member.member_id,
          reservation_id:borrow.dataset.borrowReservation,
          copy_id:copy.copy_id
        })
      });
      await refreshReservations();
      await refreshLoans();
      showToast("Loan checked out");
      switchView("loans");
    } catch (error) { showToast(error.message); }
  }
  const cancel = event.target.closest("[data-cancel-reservation]");
  if (cancel) {
    try {
      await api(`/reservations/reservations/${cancel.dataset.cancelReservation}`, {method:"DELETE"});
      await refreshReservations();
      showToast("Hold cancelled");
    } catch (error) { showToast(error.message); }
  }
  const returnButton = event.target.closest("[data-return-loan]");
  if (returnButton) {
    try {
      await api(`/loans/loans/${returnButton.dataset.returnLoan}/return`, {method:"POST"});
      await refreshLoans();
      showToast("Book returned");
    } catch (error) { showToast(error.message); }
  }
});

async function checkServices() {
  try {
    await Promise.all([
      api("/member/ready"),
      api("/catalog/ready"),
      api("/reservations/ready"),
      api("/loans/ready"),
      api("/availability/ready")
    ]);
    $("#serviceDot").classList.remove("offline");
  } catch { $("#serviceDot").classList.add("offline"); }
}

const saved = JSON.parse(localStorage.getItem("bibliothecaMember") || "null");
if (saved) signIn(saved.name, saved.email).catch(error => {
  localStorage.removeItem("bibliothecaMember");
  showToast(error.message);
});
checkServices();
