// ===============================
// Emergency Contacts Management
// ===============================

const API_URL = "/api/emergency_contacts";

let contacts = [];

// ===============================
// Load Contacts
// ===============================
async function loadContacts() {

    try {

        const response = await fetch(API_URL);
        contacts = await response.json();

        renderTable(contacts);

    }

    catch (error) {

        console.error(error);
        alert("Unable to load contacts.");

    }

}

// ===============================
// Render Table
// ===============================
function renderTable(data) {

    const tbody = document.getElementById("contactsBody");

    tbody.innerHTML = "";

    data.forEach(contact => {

        let priority = "Primary";

        if (contact.priority == 2)
            priority = "Secondary";

        if (contact.priority == 3)
            priority = "Backup";

        tbody.innerHTML += `

        <tr>

            <td>${contact.id}</td>

            <td>${contact.name}</td>

            <td>${contact.role || "-"}</td>

            <td>${contact.phone}</td>

            <td>${contact.email || "-"}</td>

            <td>${contact.camera_zone || "-"}</td>

            <td>${priority}</td>

            <td>

                <button onclick="editContact(${contact.id})">
                    Edit
                </button>

                <button onclick="deleteContact(${contact.id})">
                    Delete
                </button>

            </td>

        </tr>

        `;

    });

}

// ===============================
// Add Contact
// ===============================
document.getElementById("contactForm").addEventListener("submit", async function(e){

    e.preventDefault();

    const contact = {

        name: document.getElementById("name").value,

        role: document.getElementById("role").value,

        phone: document.getElementById("phone").value,

        email: document.getElementById("email").value,

        camera_zone: document.getElementById("camera_zone").value,

        priority: parseInt(document.getElementById("priority").value)

    };

    const response = await fetch(API_URL,{

        method:"POST",

        headers:{
            "Content-Type":"application/json"
        },

        body:JSON.stringify(contact)

    });

    if(response.ok){

        alert("Contact Added Successfully.");

        document.getElementById("contactForm").reset();

        loadContacts();

    }

    else{

        alert("Failed to add contact.");

    }

});

// ===============================
// Search
// ===============================
document.getElementById("searchInput").addEventListener("keyup",function(){

    const keyword = this.value.toLowerCase();

    const filtered = contacts.filter(c =>

        c.name.toLowerCase().includes(keyword) ||

        (c.role || "").toLowerCase().includes(keyword) ||

        (c.camera_zone || "").toLowerCase().includes(keyword)

    );

    renderTable(filtered);

});

// ===============================
// Delete
// ===============================
async function deleteContact(id){

    if(!confirm("Delete this contact?"))
        return;

    const response = await fetch(API_URL+"/"+id,{

        method:"DELETE"

    });

    if(response.ok){

        loadContacts();

    }

}

// ===============================
// Edit Contact
// ===============================
function editContact(id){

    const c = contacts.find(x=>x.id===id);

    if(!c)
        return;

    document.getElementById("editId").value=c.id;

    document.getElementById("editName").value=c.name;

    document.getElementById("editRole").value=c.role;

    document.getElementById("editPhone").value=c.phone;

    document.getElementById("editEmail").value=c.email;

    document.getElementById("editZone").value=c.camera_zone;

    document.getElementById("editPriority").value=c.priority;

    document.getElementById("editModal").style.display="block";

}

// ===============================
// Close Modal
// ===============================
function closeModal(){

    document.getElementById("editModal").style.display="none";

}

// ===============================
// Update Contact
// ===============================
document.getElementById("editForm").addEventListener("submit",async function(e){

    e.preventDefault();

    const id=document.getElementById("editId").value;

    const updated={

        name:document.getElementById("editName").value,

        role:document.getElementById("editRole").value,

        phone:document.getElementById("editPhone").value,

        email:document.getElementById("editEmail").value,

        camera_zone:document.getElementById("editZone").value,

        priority:parseInt(document.getElementById("editPriority").value)

    };

    const response=await fetch(API_URL+"/"+id,{

        method:"PUT",

        headers:{
            "Content-Type":"application/json"
        },

        body:JSON.stringify(updated)

    });

    if(response.ok){

        alert("Contact Updated.");

        closeModal();

        loadContacts();

    }

    else{

        alert("Update Failed.");

    }

});

// ===============================
// Initial Load
// ===============================
window.onload=function(){

    loadContacts();

};