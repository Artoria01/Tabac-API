import discord
from discord.ext import commands
from discord.ui import Select, View, Button
from datetime import datetime
from flask import Flask
from threading import Thread
from pymongo import MongoClient
import os
import asyncio
import pytz

# Crée un objet intents avec les intentions par défaut
intents = discord.Intents.default()

# Active l'intention pour le contenu des messages
intents.message_content = True

# Crée le bot avec ces intentions
bot = commands.Bot(command_prefix="!", intents=intents)

# Récupère l'URL de connexion depuis la variable d'environnement
mongo_url = os.getenv('MONGO_URL')

# Crée la connexion MongoDB
client = MongoClient(mongo_url)

# Accède à la base de données
db = client['BotAPI']
admins_collection = db['admins']
vehicles_collection = db['vehicles']

# Variable globale pour le message de la liste des véhicules
list_message = None
current_page = 1

# Ajouter un admin par défaut si pas déjà dans la base de données
def add_default_admin():
    default_admin_id = "652050350454472734"  # ID OWNER
    if admins_collection.count_documents({"_id": default_admin_id}) == 0:
        admins_collection.insert_one({"_id": default_admin_id})

add_default_admin()

# Vérifier si un utilisateur est admin
def is_admin(user_id):
    return admins_collection.count_documents({"_id": str(user_id)}) > 0

# Vérifier si un utilisateur est propriétaire d'un véhicule
def is_owner(user_id, plaque):
    vehicle = vehicles_collection.find_one({"plaque": plaque})
    return vehicle and vehicle["owner_id"] == user_id

# Fonction pour créer l'embed de la liste des véhicules avec "Modifier par"
def create_vehicle_embed(page_number=1):
    embed = discord.Embed(title="Liste des véhicules", color=discord.Color.blue())

    vehicles = vehicles_collection.find().skip((page_number - 1) * 10).limit(10)  # Affiche les véhicules de la page
    if not vehicles:
        embed.add_field(name="Aucun véhicule", value="Il n'y a aucun véhicule enregistré.")
    else:
        for vehicle in vehicles:
            emoji = "🔴" if vehicle["state"] == "garage" else "🔵"
            owner = vehicle['owner']
            last_changed = vehicle.get("last_changed", "`Non défini`")  # Utilise la date de changement stockée
            modified_by = vehicle.get("last_modified_by", "`Non défini`")  # Dernière personne à avoir modifié l'état
            public = "Oui" if vehicle.get("public", False) else "Non"  # Vérifier si le véhicule est public

            embed.add_field(
                name=f"{emoji} Plaque : `{vehicle['plaque']}`",
                value=(
                    f"Propriétaire : `{owner}`\n"
                    f"État : `{vehicle['state']}`\n"
                    f"Dernière modification le : {last_changed}\n"
                    f"Modifié par : `{modified_by}`\n"
                    f"Véhicule public : `{public}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                inline=False
            )

    # Ajouter les boutons de pagination
    total_pages = calculate_total_pages()
    embed.set_footer(text=f"Page {page_number}/{total_pages}")

    return embed

# Dictionnaire pour gérer les verrous par message avec asyncio.Lock()
pagination_locks = {}

# Fonction pour verrouiller un message avec délai d'attente
async def lock_pagination(message_id, timeout=5):
    if message_id not in pagination_locks:
        pagination_locks[message_id] = asyncio.Lock()

    lock = pagination_locks[message_id]

    # Tente de verrouiller l'accès au message avec un délai d'attente
    try:
        await asyncio.wait_for(lock.acquire(), timeout)
        return lock
    except asyncio.TimeoutError:
        return None  # Si le délai est dépassé, retourner None

# Fonction pour déverrouiller un message spécifique
def unlock_pagination(message_id):
    lock = pagination_locks.get(message_id)
    if lock:
        lock.release()

# Fonction de mise à jour de la liste avec gestion du verrou
async def update_vehicle_list(ctx, page_number=1):
    global current_page, list_message
    current_page = page_number

    if list_message:
        lock = await lock_pagination(list_message.id)  # Acquiert le verrou

    try:
        embed = create_vehicle_embed(page_number)

        # Créer les boutons de pagination
        prev_button = Button(label="◀️ Précédent", style=discord.ButtonStyle.primary, disabled=page_number == 1)
        next_button = Button(label="Suivant ▶️", style=discord.ButtonStyle.primary, disabled=page_number == calculate_total_pages())

        # Callback pour les boutons
        async def prev_callback(interaction):
            await interaction.response.defer()
            await update_vehicle_list(ctx, page_number - 1)

        async def next_callback(interaction):
            await interaction.response.defer()
            await update_vehicle_list(ctx, page_number + 1)

        prev_button.callback = prev_callback
        next_button.callback = next_callback

        # Créer la vue et ajouter les boutons
        view = View(timeout=None)
        view.add_item(prev_button)
        view.add_item(next_button)

        if list_message:
            await list_message.edit(embed=embed, view=view)
        else:
            # Si le message n'existe pas encore, l'envoyer
            message = await ctx.send(embed=embed, view=view)
            list_message = message

    finally:
        unlock_pagination(list_message.id)  # Libère toujours le verrou après l'opération

# Fonction pour gérer la pagination avec un menu déroulant
async def update_vehicle_list_with_dropdown(ctx, page_number=1):
    global current_page, list_message
    current_page = page_number

    embed = create_vehicle_embed(page_number)
    vehicles = list(vehicles_collection.find().skip((page_number - 1) * 10).limit(10))  # Récupérer les véhicules de la page

    # Créer un select menu avec les véhicules de la page
    select = Select(
        placeholder="Choisissez un véhicule",
        options=[discord.SelectOption(label=f"Plaque: {vehicle['plaque']}", value=vehicle['plaque']) for vehicle in vehicles]
    )

    # Fonction pour gérer la sélection du nouvel état pour les véhicules publics
    async def select_callback(interaction):
        selected_plaque = select.values[0]
        vehicle = vehicles_collection.find_one({"plaque": selected_plaque})

        # Vérifie si le véhicule est public ou si l'utilisateur est admin/possède le véhicule
        if not (vehicle.get("public", False) or is_admin(interaction.user.id) or is_owner(interaction.user.id, selected_plaque)):
            await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état de ce véhicule.", ephemeral=True)
            return

        # Affichage du menu pour modifier l'état
        state_select = Select(
            placeholder="Sélectionnez l'état du véhicule",
            options=[
                discord.SelectOption(label="Garage", value="garage"),
                discord.SelectOption(label="Sorti", value="sorti")
            ]
        )

        async def state_select_callback(interaction):
            new_state = state_select.values[0]
            vehicles_collection.update_one(
                {"plaque": selected_plaque}, 
                {"$set": {
                    "state": new_state, 
                    "last_changed": get_french_time(), 
                    "last_modified_by": interaction.user.name
                }}
            )
            await update_vehicle_list_with_dropdown(interaction, current_page)
            await update_bot_activity()  # Met à jour l'activité du bot après modification
            await interaction.response.send_message(f"✅ L'état du véhicule {selected_plaque} a été modifié en {new_state}.", ephemeral=True)

        state_select.callback = state_select_callback
        view = View(timeout=None)
        view.add_item(state_select)

        await interaction.response.send_message("Sélectionnez un nouvel état pour ce véhicule.", view=view, ephemeral=True)

    select.callback = select_callback
    view = View(timeout=None)
    view.add_item(select)

    # Créer les boutons de pagination
    prev_button = Button(label="◀️ Précédent", style=discord.ButtonStyle.primary, disabled=page_number == 1)
    next_button = Button(label="Suivant ▶️", style=discord.ButtonStyle.primary, disabled=page_number == calculate_total_pages())

    async def prev_callback(interaction):
        await interaction.response.defer()
        await update_vehicle_list_with_dropdown(ctx, page_number - 1)

    async def next_callback(interaction):
        await interaction.response.defer()
        await update_vehicle_list_with_dropdown(ctx, page_number + 1)

    prev_button.callback = prev_callback
    next_button.callback = next_callback

    # Ajouter les boutons à la vue
    view.add_item(prev_button)
    view.add_item(next_button)

    # Vérification si list_message existe
    if list_message is None:
        # Si list_message n'existe pas encore, l'envoyer
        message = await ctx.send(embed=embed, view=view)
        list_message = message
    else:
        try:
            # Si list_message existe, il est mis à jour avec le nouvel embed et vue
            await list_message.edit(embed=embed, view=view)
            print("Message de la liste mis à jour.")
        except discord.errors.NotFound:
            # Si le message a été supprimé, on envoie un nouveau message
            list_message = await ctx.send(embed=embed, view=view)
            print("Le message a été supprimé, un nouveau message est envoyé.")

# Commande pour voir la liste des véhicules avec pagination et menu déroulant
@bot.command()
async def list_vehicles(ctx):
    await update_vehicle_list_with_dropdown(ctx, page_number=1)

# Fonction pour mettre à jour l'activité du bot
async def update_bot_activity():
    total_garage = vehicles_collection.count_documents({"state": "garage"})
    total_sorti = vehicles_collection.count_documents({"state": "sorti"})
    activity = discord.Game(f"🔴 {total_garage} rangés | 🔵 {total_sorti} sortis")
    await bot.change_presence(activity=activity)

# Commande pour ajouter un véhicule
@bot.tree.command(name="add_vehicle", description="Ajoutez un véhicule pour un membre (Admin uniquement)")
async def add_vehicle(interaction: discord.Interaction, plaque: str, member: discord.Member):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission d'ajouter un véhicule.", ephemeral=True)
        return
    if vehicles_collection.count_documents({"plaque": plaque}) > 0:
        await interaction.response.send_message(f"⚠️ Le véhicule avec la plaque {plaque} existe déjà.", ephemeral=True)
        return
    vehicles_collection.insert_one({"plaque": plaque, "owner": member.name, "owner_id": member.id, "state": "garage"})
    await update_vehicle_list_with_dropdown(interaction, page_number=1)  # Remplace ici
    await update_bot_activity()  # Met à jour l'activité du bot après ajout
    await interaction.response.send_message(f"✅ Véhicule {plaque} ajouté avec succès.", ephemeral=True)

# Commande pour supprimer un véhicule
@bot.tree.command(name="remove_vehicle", description="Supprimez un véhicule existant (Admin uniquement)")
async def remove_vehicle(interaction: discord.Interaction, plaque: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission de supprimer un véhicule.", ephemeral=True)
        return
    if vehicles_collection.count_documents({"plaque": plaque}) == 0:
        await interaction.response.send_message(f"⚠️ Aucun véhicule trouvé avec la plaque {plaque}.", ephemeral=True)
        return
    vehicles_collection.delete_one({"plaque": plaque})
    await update_vehicle_list_with_dropdown(interaction, page_number=1)  # Remplace ici
    await update_bot_activity()  # Met à jour l'activité du bot après suppression
    await interaction.response.send_message(f"✅ Véhicule {plaque} supprimé avec succès.", ephemeral=True)

# Commande pour rendre un véhicule public ou le retirer de la visibilité publique
@bot.tree.command(name="public", description="Rendre un véhicule public ou retirer sa visibilité publique (Admin uniquement)")
async def make_public(interaction: discord.Interaction, plaque: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier la visibilité publique d'un véhicule.", ephemeral=True)
        return

    vehicle = vehicles_collection.find_one({"plaque": plaque})
    if not vehicle:
        await interaction.response.send_message(f"⚠️ Aucun véhicule trouvé avec la plaque {plaque}.", ephemeral=True)
        return

    # Vérifier si le véhicule est déjà public
    is_public = vehicle.get("public", False)

    # Inverser l'état de "public" : si le véhicule est public, on le rend privé, sinon on le rend public
    new_public_state = not is_public

    # Mettre à jour le champ "public" du véhicule
    vehicles_collection.update_one(
        {"plaque": plaque},
        {"$set": {"public": new_public_state}}
    )

    # Répondre avec un message selon le nouvel état du véhicule
    if new_public_state:
        await interaction.response.send_message(f"✅ Le véhicule {plaque} est maintenant public.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Le véhicule {plaque} n'est plus public.", ephemeral=True)

    # Mettre à jour la liste des véhicules et l'activité du bot
    await update_vehicle_list_with_dropdown(interaction, page_number=1)
    await update_bot_activity()  # Met à jour l'activité du bot après modification



# Garder l'activité du bot à jour à chaque démarrage
@bot.event
async def on_ready():
    await bot.tree.sync()
    await update_bot_activity()  # Met à jour l'activité du bot dès le démarrage
    print(f'{bot.user} est prêt et les commandes Slash sont synchronisées.')

# Garder le bot actif
app = Flask('')

@app.route('/')
def home():
    return "Le bot fonctionne !"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

# Lancer le bot
bot.run(os.getenv("DISCORD_TOKEN"))
