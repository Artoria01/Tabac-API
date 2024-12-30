import discord
from discord.ext import commands
import json
import os
from discord.ui import Select, View
from flask import Flask
from threading import Thread

# Création du bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Fichiers de sauvegarde
DATA_FILE = "vehicles.json"
ADMINS_FILE = "admins.json"

# Charger ou sauvegarder les données
def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

vehicles = load_json(DATA_FILE)
admins = load_json(ADMINS_FILE)

# Variable globale pour le message de la liste des véhicules
list_message = None

# Ajouter un admin par défaut si pas déjà dans le fichier
def add_default_admin():
    default_admin_id = "652050350454472734"  # ID OWNER
    if default_admin_id not in admins:
        admins[default_admin_id] = {}
        save_json(ADMINS_FILE, admins)

add_default_admin()

# Vérifier si un utilisateur est admin
def is_admin(user_id):
    return str(user_id) in admins  # Utiliser str() pour la comparaison

# Vérifier si un utilisateur est propriétaire d'un véhicule
def is_owner(user_id, plaque):
    return plaque in vehicles and vehicles[plaque]["owner_id"] == user_id

# Fonction pour créer l'embed de la liste des véhicules
def create_vehicle_embed():
    embed = discord.Embed(title="Liste des véhicules", color=discord.Color.blue())
    if not vehicles:
        embed.add_field(name="Aucun véhicule", value="Il n'y a aucun véhicule enregistré.")
    else:
        for plaque, info in vehicles.items():
            emoji = "🔴" if info["state"] == "garage" else "🔵"

            owner = info['owner']
            member = None

            # Parcours des guildes où le bot est présent pour récupérer le membre
            for guild in bot.guilds:
                member = guild.get_member(info['owner_id'])
                if member:
                    break

            # Si le membre est trouvé, on utilise son 'nick' (pseudo spécifique au serveur) ou son 'name' (nom global)
            if member:
                owner = member.nick if member.nick else member.name
            else:
                # Si le membre n'est pas trouvé, utiliser l'info sauvegardée (propriétaire par défaut)
                owner = info['owner']  

            embed.add_field(
                name=f"{emoji} Plaque : `{plaque}`",
                value=f"Propriétaire : `{owner}`\nÉtat : `{info['state']}`",
                inline=False
            )

    return embed

# Fonction pour mettre à jour l'embed de la liste des véhicules
async def update_list_message():
    global list_message
    if list_message:
        try:
            # Tente de rééditer l'embed existant si le message est toujours présent
            embed = create_vehicle_embed()
            await list_message.edit(embed=embed)
        except discord.NotFound:
            # Si le message a été supprimé (embed expiré), on le recrée
            print("Le message de la liste des véhicules a expiré ou a été supprimé, création d'un nouveau.")
            list_message = await list_message.channel.send(embed=create_vehicle_embed())
    else:
        # Si list_message est None (pas encore de message), créer un message
        print("Le message de la liste des véhicules n'a pas encore été envoyé, création d'un nouveau.")
        list_message = await list_message.channel.send(embed=create_vehicle_embed())

    # Mettre à jour l'activité du bot
    await update_bot_activity()

# Fonction pour mettre à jour l'activité du bot
async def update_bot_activity():
    total_garage = sum(1 for v in vehicles.values() if v["state"] == "garage")
    total_sorti = sum(1 for v in vehicles.values() if v["state"] == "sorti")
    activity = discord.Game(f"🔴 {total_garage} rangés | 🔵 {total_sorti} sortis")
    await bot.change_presence(activity=activity)

# Commande pour ajouter un véhicule
@bot.tree.command(name="add_vehicle", description="Ajoutez un véhicule pour un membre (Admin uniquement)")
async def add_vehicle(interaction: discord.Interaction, plaque: str, member: discord.Member):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission d'ajouter un véhicule.", ephemeral=True)
        return
    if plaque in vehicles:
        await interaction.response.send_message(f"⚠️ Le véhicule avec la plaque {plaque} existe déjà.", ephemeral=True)
        return
    vehicles[plaque] = {"owner": member.name, "owner_id": member.id, "state": "garage"}
    save_json(DATA_FILE, vehicles)

    await update_list_message()
    await interaction.response.send_message(f"✅ Véhicule `{plaque}` ajouté avec succès.", ephemeral=True)

# Commande pour supprimer un véhicule
@bot.tree.command(name="remove_vehicle", description="Supprimez un véhicule existant (Admin uniquement)")
async def remove_vehicle(interaction: discord.Interaction, plaque: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission de supprimer un véhicule.", ephemeral=True)
        return
    if plaque not in vehicles:
        await interaction.response.send_message(f"⚠️ Aucun véhicule trouvé avec la plaque {plaque}.", ephemeral=True)
        return
    del vehicles[plaque]
    save_json(DATA_FILE, vehicles)

    await update_list_message()
    await interaction.response.send_message(f"✅ Véhicule `{plaque}` supprimé avec succès.", ephemeral=True)

# Commande pour changer l'état d'un véhicule
@bot.tree.command(name="change_vehicle_state", description="Changez l'état d'un véhicule (Admin uniquement)")
async def change_vehicle_state(interaction: discord.Interaction, plaque: str, new_state: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état d'un véhicule.", ephemeral=True)
        return
    if plaque not in vehicles:
        await interaction.response.send_message(f"⚠️ Aucun véhicule trouvé avec la plaque {plaque}.", ephemeral=True)
        return
    if new_state not in ["garage", "sorti"]:
        await interaction.response.send_message("⚠️ État invalide. Choisissez entre 'garage' ou 'sorti'.", ephemeral=True)
        return

    vehicles[plaque]["state"] = new_state
    save_json(DATA_FILE, vehicles)

    await update_list_message()
    await interaction.response.send_message(f"✅ État du véhicule `{plaque}` modifié en `{new_state}`.", ephemeral=True)

# Commande pour voir la liste des véhicules
@bot.command()
async def list_vehicles(ctx):
    global list_message

    embed = create_vehicle_embed()
    message = await ctx.send(embed=embed)

    # Sauvegarder le message pour les mises à jour futures
    list_message = message

    # Ajouter un menu déroulant pour choisir un véhicule
    select = Select(
        placeholder="Choisissez un véhicule",
        options=[discord.SelectOption(label=f"Plaque: {plaque}", value=plaque) for plaque in vehicles]
    )

    async def select_callback(interaction):
        selected_plaque = select.values[0]
        vehicle = vehicles[selected_plaque]

        # Vérifier si l'utilisateur est admin ou propriétaire du véhicule
        if not (is_admin(interaction.user.id) or is_owner(interaction.user.id, selected_plaque)):
            await interaction.response.send_message("❌ Vous n'avez pas la permission de modifier l'état de ce véhicule.", ephemeral=True)
            return

        # Créer un menu déroulant pour choisir l'état
        state_select = Select(
            placeholder="Sélectionnez l'état du véhicule",
            options=[
                discord.SelectOption(label="Garage", value="garage"),
                discord.SelectOption(label="Sorti", value="sorti")
            ]
        )

        async def state_select_callback(interaction):
            new_state = state_select.values[0]
            vehicles[selected_plaque]["state"] = new_state
            save_json(DATA_FILE, vehicles)

            await update_list_message()
            await interaction.response.send_message(f"✅ L'état du véhicule `{selected_plaque}` a été modifié en `{new_state}`.", ephemeral=True)

        state_select.callback = state_select_callback
        view = View(timeout=None)  # Le menu ne va jamais expirer
        view.add_item(state_select)

        await interaction.response.send_message("Sélectionnez un nouvel état pour ce véhicule.", view=view, ephemeral=True)

    select.callback = select_callback
    view = View(timeout=None)  # Le menu ne va jamais expirer
    view.add_item(select)

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
