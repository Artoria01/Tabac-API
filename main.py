import discord
from discord.ext import commands
from discord.ui import Select, View, Button
from flask import Flask
from threading import Thread
from pymongo import MongoClient
from datetime import datetime
import os
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

# Fonction pour formater la date avec l'heure en fuseau horaire de Paris
def format_date(date_str):
    if date_str:
        # Convertir la chaîne en datetime
        date_time = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return date_time.strftime('%H:%M - %d/%m')  # Format horaire souhaité
    return "Inconnu"

# Fonction pour créer l'embed de la liste des véhicules
def create_vehicle_embed():
    embed = discord.Embed(title="Liste des véhicules", color=discord.Color.blue())
    vehicles = vehicles_collection.find()
    if not vehicles:
        embed.add_field(name="Aucun véhicule", value="`Il n'y a aucun véhicule enregistré.`")
    else:
        for vehicle in vehicles:
            emoji = "🔴" if vehicle["state"] == "garage" else "🔵"
            owner = vehicle['owner']
            details = [f"Propriétaire : `{owner}`", f"État : `{vehicle['state']}`"]

            if vehicle.get('personnel') == 'oui':
                last_changed = vehicle.get('last_changed_date')
                if last_changed:
                    details.append(f"Dernier changement le : `{format_date(last_changed)}`")
            else:
                details.append(f"🅿︎** ┄┄ Véhicule Public ┄┄ **🅿︎")
                last_changed_by = vehicle.get('last_changed_by', "`Inconnu`")
                details.append(f"Dernier changement par : `{last_changed_by}`")
                last_changed = vehicle.get('last_changed_date')
                if last_changed:
                    details.append(f"Dernier changement le : `{format_date(last_changed)}`")
                else:
                    details.append("Dernier changement le : `Non défini`")

            # Ajouter les champs à l'embed
            embed.add_field(name=f"{emoji} Plaque : `{vehicle['plaque']}`", value="\n".join(details), inline=False)
            embed.add_field(name="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
    return embed

# Fonction pour mettre à jour l'embed de la liste des véhicules
async def update_list_message():
    global list_message
    # Si list_message existe déjà, tenter de le rééditer, sinon le créer
    if list_message:
        try:
            embed = create_vehicle_embed()
            await list_message.edit(embed=embed)
        except discord.NotFound:
            print("Le message de la liste des véhicules a expiré ou a été supprimé, création d'un nouveau.")
            # Recréer un message si l'ancien a été supprimé
            list_message = await list_message.channel.send(embed=create_vehicle_embed())
    else:
        print("Le message de la liste des véhicules n'a pas encore été envoyé, création d'un nouveau.")
        # Trouver un canal pour envoyer le message (remplacer par ton ID de canal)
        channel = bot.get_channel(1322671748537258014)  # Remplace TON_CANAL_ID par l'ID de ton canal
        if channel:
            list_message = await channel.send(embed=create_vehicle_embed())

    # Mettre à jour les options du menu déroulant
    select = Select(
        placeholder="Choisissez un véhicule",
        options=[discord.SelectOption(label=f"Plaque: {vehicle['plaque']}", value=vehicle['plaque']) for vehicle in vehicles_collection.find()]
    )

    # Callback pour la sélection du véhicule
    async def select_callback(interaction):
        selected_plaque = select.values[0]
        vehicle = vehicles_collection.find_one({"plaque": selected_plaque})

        # Vérifier si l'utilisateur est admin ou propriétaire
        if not (is_admin(interaction.user.id) or is_owner(interaction.user.id, selected_plaque)):
            await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état de ce véhicule.", ephemeral=True)
            return

        # Création d'un menu déroulant pour changer l'état du véhicule
        state_select = Select(
            placeholder="Sélectionnez l'état du véhicule",
            options=[
                discord.SelectOption(label="Garage", value="garage"),
                discord.SelectOption(label="Sorti", value="sorti")
            ],
            custom_id=selected_plaque  # Passer la plaque via custom_id
        )

        # Lier la callback à la sélection de l'état
        state_select.callback = state_select_callback

        # Afficher le menu déroulant pour la modification de l'état
        view = View(timeout=None)
        view.add_item(state_select)

        await interaction.response.send_message("Sélectionnez un nouvel état pour ce véhicule.", view=view, ephemeral=True)

    select.callback = select_callback
    view = View(timeout=None)
    view.add_item(select)

    # Mettre à jour le message avec le menu de sélection du véhicule
    await list_message.edit(view=view)

    await update_bot_activity()

# Fonction pour mettre à jour l'activité du bot
async def update_bot_activity():
    total_garage = vehicles_collection.count_documents({"state": "garage"})
    total_sorti = vehicles_collection.count_documents({"state": "sorti"})
    activity = discord.Game(f"🔴 {total_garage} rangés | 🔵 {total_sorti} sortis")
    await bot.change_presence(activity=activity)

# Commande pour ajouter un véhicule
@bot.tree.command(name="add_vehicle", description="Ajoutez un véhicule pour un membre (Admin uniquement)")
async def add_vehicle(interaction: discord.Interaction, plaque: str, member: discord.Member, personnel: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission d'ajouter un véhicule.", ephemeral=True)
        return
    if vehicles_collection.count_documents({"plaque": plaque}) > 0:
        await interaction.response.send_message(f"⚠️ Le véhicule avec la plaque {plaque} existe déjà.", ephemeral=True)
        return
    vehicle = {
        "plaque": plaque,
        "owner": member.name,
        "owner_id": member.id,
        "state": "garage",
        "personnel": personnel.lower(),
        "last_changed_by": interaction.user.name,
        "last_changed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    vehicles_collection.insert_one(vehicle)
    await update_list_message()  # Mettre à jour le menu déroulant après l'ajout
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
    await update_list_message()  # Mettre à jour le menu déroulant après la suppression
    await interaction.response.send_message(f"✅ Véhicule {plaque} supprimé avec succès.", ephemeral=True)

# Fonction pour changer l'état d'un véhicule
@bot.tree.command(name="change_vehicle_state", description="Changez l'état d'un véhicule (Admin uniquement)")
async def change_vehicle_state(interaction: discord.Interaction, plaque: str, new_state: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état d'un véhicule.", ephemeral=True)
        return
    vehicle = vehicles_collection.find_one({"plaque": plaque})
    if not vehicle:
        await interaction.response.send_message(f"⚠️ Aucun véhicule trouvé avec la plaque {plaque}.", ephemeral=True)
        return
    if new_state not in ["garage", "sorti"]:
        await interaction.response.send_message("⚠️ État invalide. Choisissez entre 'garage' ou 'sorti'.", ephemeral=True)
        return

    # Obtenir l'heure actuelle en heure française
    paris_tz = pytz.timezone('Europe/Paris')
    current_time = datetime.now(paris_tz).strftime("%Y-%m-%d %H:%M:%S")

    # Mettre à jour l'état du véhicule
    vehicles_collection.update_one(
        {"plaque": plaque}, 
        {
            "$set": {
                "state": new_state,
                "last_changed_by": interaction.user.name,  # Met à jour la personne ayant fait la modification
                "last_changed_date": current_time  # Met à jour la date du changement en heure locale française
            }
        }
    )
    await update_list_message()
    await interaction.response.send_message(f"✅ État du véhicule {plaque} modifié en {new_state}.", ephemeral=True)

# Callback pour la sélection de l'état dans le menu déroulant
async def state_select_callback(interaction):
    selected_plaque = interaction.data["custom_id"]  # Utilisation de custom_id pour obtenir la plaque
    new_state = interaction.data["values"][0]  # L'état sélectionné

    # Obtenir l'heure actuelle en heure française
    paris_tz = pytz.timezone('Europe/Paris')
    current_time = datetime.now(paris_tz).strftime("%Y-%m-%d %H:%M:%S")

    # Mettre à jour l'état dans la base de données avec les nouvelles informations
    vehicles_collection.update_one(
        {"plaque": selected_plaque},
        {
            "$set": {
                "state": new_state,
                "last_changed_by": interaction.user.name,  # Mise à jour de la personne qui a effectué la modification
                "last_changed_date": current_time  # Mise à jour de la date avec l'heure locale française
            }
        }
    )

    # Mettre à jour le message de la liste des véhicules
    await update_list_message()
    await interaction.response.send_message(f"✅ L'état du véhicule {selected_plaque} a été modifié en {new_state}.", ephemeral=True)

# Commande pour voir la liste des véhicules
@bot.command()
async def list_vehicles(ctx):
    global list_message
    embed = create_vehicle_embed()
    message = await ctx.send(embed=embed)
    list_message = message

    # Création du menu déroulant pour choisir un véhicule
    select = Select(
        placeholder="Choisissez un véhicule",
        options=[discord.SelectOption(label=f"Plaque: {vehicle['plaque']}", value=vehicle['plaque']) for vehicle in vehicles_collection.find()]
    )

    # Callback pour la sélection du véhicule
    async def select_callback(interaction):
        selected_plaque = select.values[0]
        vehicle = vehicles_collection.find_one({"plaque": selected_plaque})

        # Vérifier si l'utilisateur est admin ou propriétaire
        if not (is_admin(interaction.user.id) or is_owner(interaction.user.id, selected_plaque)):
            await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état de ce véhicule.", ephemeral=True)
            return

        # Création d'un menu déroulant pour changer l'état du véhicule
        state_select = Select(
            placeholder="Sélectionnez l'état du véhicule",
            options=[
                discord.SelectOption(label="Garage", value="garage"),
                discord.SelectOption(label="Sorti", value="sorti")
            ],
            custom_id=selected_plaque  # Passer la plaque via custom_id
        )

        # Lier la callback à la sélection de l'état
        state_select.callback = state_select_callback

        # Afficher le menu déroulant pour la modification de l'état
        view = View(timeout=None)
        view.add_item(state_select)

        await interaction.response.send_message("Sélectionnez un nouvel état pour ce véhicule.", view=view, ephemeral=True)

    select.callback = select_callback
    view = View(timeout=None)
    view.add_item(select)

    # Mettre à jour le message avec le menu de sélection du véhicule
    await message.edit(view=view)

# Synchroniser les commandes Slash à chaque démarrage
@bot.event
async def on_ready():
    await bot.tree.sync()
    await update_bot_activity()
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
