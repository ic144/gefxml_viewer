"""
Script om sonderingen en boringen vanuit GEF of XML (BRO) in te lezen en te plotten
"""

__author__ = "Thomas van der Linden"
__credits__ = ""
__license__ = "MPL-2.0"
__version__ = ""
__maintainer__ = "Thomas van der Linden"
__email__ = "t.van.der.linden@amsterdam.nl"
__status__ = "Dev"

from cmath import isnan
from dataclasses import dataclass
from operator import is_
from typing import OrderedDict
import pandas as pd
from io import StringIO
import numpy as np
import re
from matplotlib.gridspec import GridSpec
import matplotlib.pyplot as plt
from datetime import date, datetime
from shapely.geometry import Point
import geopandas as gpd
from xml.etree.ElementTree import ElementTree

@dataclass
class Test():
    def __init__(self):
        self.type = str()
    
    def load_gef(self, gefFile):
        procedure_pattern = re.compile(r'#PROCEDURECODE\s*=\s*(?P<procedure>.*)\s*')
        report_pattern = re.compile(r'#REPORTCODE\s*=\s*(?P<report>.*)\s*')
        
        with open(gefFile) as f:
            raw_gef = f.read()
        try:
            match = re.search(procedure_pattern, raw_gef)
            procedure = match.group('procedure')
            if 'CPT' in procedure.upper():
                return 'cpt'
            elif 'BORE' in procedure.upper():
                return 'bore'
        except:
            pass

        try:
            match = re.search(report_pattern, raw_gef)
            report = match.group('report')
            if 'CPT' in report.upper():
                return 'cpt'
            elif 'BORE' in report.upper():
                return 'bore'
        except:
            pass

    def load_xml(self, xmlFile):
        with open(xmlFile) as f:
            raw_xml = f.read()

        # TODO: dit kan beter, maar er lijkt niet echt een standaard te zijn
        if 'CPTSTANDARD' in raw_xml.upper():
            return 'cpt'
        else:
            return 'bore'


@dataclass
class Cpt():
    def __init__(self):
        self.easting = None
        self.northing = None
        self.groundlevel = -9999
        self.srid = None
        self.testid = None
        self.date = None
        self.finaldepth = None
        self.removedlayers = {}
        self.data = None
        self.filename = None
        self.companyid = None
        self.projectid = None
        self.projectname = None

    def load_xml(self, xmlFile):

        # lees een CPT in vanuit een BRO XML
        tree = ElementTree()
        tree.parse(xmlFile)
        root = tree.getroot()

        for element in root.iter():

            if 'broId' in element.tag:
                self.testid = element.text

            if 'deliveredLocation' in element.tag:
                location = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                self.easting = float(location['pos'].split()[0])
                self.northing = float(location['pos'].split()[1])

            elif 'deliveredVerticalPosition' in element.tag:
                verticalPosition = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                self.groundlevel = float(verticalPosition['offset'])

            elif 'finalDepth' in element.tag:
                self.finaldepth = float(element.text)

            elif 'researchReportDate' in element.tag:
                date = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                try: # een datum is niet verplicht
                    self.date = datetime.strptime(date['date'], '%Y-%m-%d')
                except:
                    pass

            # er kan een dissipatietest inzitten, hiermee wordt alleen de cpt ingelezen. Die staat in dissipationTest
            elif 'conePenetrationTest' in element.tag: 
                for child in element.iter():
                    if 'values' in child.tag:
                        self.data = child.text

            elif 'removedLayer' in element.tag:
                # TODO: maak hier van een Bore() en plot die ook
                self.removedlayers = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}      

        filename_pattern = re.compile(r'(.*[\\/])*(?P<filename>.*)\.')
        match = re.search(filename_pattern, xmlFile)
        self.filename = match.group('filename')

        dataColumns = [
            "penetrationLength", "depth", "elapsedTime", 
            "coneResistance", "correctedConeResistance", "netConeResistance", 
            "magneticFieldStrengthX", "magneticFieldStrengthY", "magneticFieldStrengthZ", 
            "magneticFieldStrengthTotal", "electricalConductivity", 
            "inclinationEW", "inclinationNS", "inclinationX", "inclinationY", "inclinationResultant",
            "magneticInclination", "magneticDeclination",
            "localFriction",
            "poreRatio", "temperature", 
            "porePressureU1", "porePressureU2", "porePressureU3",
            "frictionRatio"]
        
        self.data = pd.read_csv(StringIO(self.data), names=dataColumns, sep=",", lineterminator=';')
        self.data = self.data.replace(-999999, np.nan)

        self.check_depth()

        self.data.sort_values(by="depth", inplace=True)

    def load_gef(self, gefFile):
        self.columnvoid_values = {}
        self.columninfo = {}
        self.columnseparator = " "
        self.recordseparator = ""
        
        # zelfde namen voor kolommen als in xml
        GEF_COLINFO = { 
            '1': 'penetrationLength',
            '2': 'coneResistance',
            '3': 'localFriction',
            '4': 'frictionRatio',
            '5': 'porePressureU1',
            '6': 'porePressureU2',
            '7': 'porePressureU3',
            '8': 'inclinationResultant',
            '9': 'inclinationNS',
            '10': 'inclinationEW',
            '11': 'depth',
            '12': 'elapsedTime',
            '13': 'correctedConeResistance',
            '14': 'netConeResistance',
            '15': 'poreRatio',
            '16': 'Nm [-]',
            '17': 'gamma [kN/m3]',
            '18': 'u0 [MPa]',
            '19': 'sigma_vo [MPa]',
            '20': 'sigma_vo_eff [MPa]',
            '21': 'inclinationX',
            '22': 'inclinationY'
        }

        filename_pattern = re.compile(r'(.*[\\/])*(?P<filename>.*)\.')
        gefid_pattern = re.compile(r'#GEFID\s*=\s*(?P<gefid>\d,\d,\d)\s*')
        xydxdy_id_pattern = re.compile(r'#XYID\s*=\s*(?P<coordsys>\d*)\s*,\s*(?P<X>\d*.?\d*)\s*,\s*(?P<Y>\d*.?\d*)\s*,\s*(?P<dx>\d*.?\d*),\s*(?P<dy>\d*.?\d*)\s*')
        xy_id_pattern = re.compile(r'#XYID\s*=\s*(?P<coordsys>\d*)\s*,\s*(?P<X>\d*.?\d*)\s*,\s*(?P<Y>\d*.?\d*)\s*')
        z_id_pattern = re.compile(r'#ZID\s*=\s*(?P<datum>\d*)\s*,\s*(?P<Z>.*)\s*')
        zdz_id_pattern = re.compile(r'#ZID\s*=\s*(?P<datum>\d*)\s*,\s*(?P<Z>.*)\s*,\s*(?P<dZ>.*)\s*')
        companyid_pattern = re.compile(r'#COMPANYID\s*=\s*(?P<companyid>.*),\s*\w*,\s*\d*\s*')
        projectid_pattern = re.compile(r'#PROJECTID\s*=\s*(?P<projectid>\d*)\s*')
        projectname_pattern = re.compile(r'#PROJECTNAME\s*=\s*(?P<projectname>.*)\s*')
        companyid_in_measurementext_pattern = re.compile(r'#MEASUREMENTTEXT\s*=\s*\d*,\s*(?P<companyid>.*),\s*boorbedrijf\s*')
        projectname_in_measurementtext_pattern = re.compile(r'#MEASUREMENTTEXT\s*=\s*\d*,\s*(?P<projectname>.*),\s*projectnaam\s*')
        startdate_pattern = re.compile(r'#STARTDATE\s*=\s*(?P<startdate>\d*,\s*\d*,\s*\d*)\s*')
        testid_pattern = re.compile(r'#TESTID\s*=\s*(?P<testid>.*)\s*')

        data_pattern = re.compile(r'#EOH\s*=\s*(?P<data>(.*\n)*)')

        columnvoid_pattern = re.compile(r'#COLUMNVOID\s*=\s*(?P<columnnr>\d*),\s*(?P<voidvalue>.*)\s*')
        columninfo_pattern = re.compile(r'#COLUMNINFO\s*=\s*(?P<columnnr>\d*),\s*(?P<unit>.*),\s*(?P<parameter>.*),\s*(?P<quantitynr>\d*)\s*')
        columnseparator_pattern = re.compile(r'#COLUMNSEPARATOR\s*=\s*(?P<columnseparator>.*)')
        recordseparator_pattern = re.compile(r'#RECORDSEPARATOR\s*=\s*(?P<recordseparator>.*)')

        with open(gefFile) as f:
            gef_raw = f.read()

        try:
            match = re.search(filename_pattern, gefFile)
            self.filename = match.group('filename')
        except:
            pass
        try:
            match = re.search(gefid_pattern, gef_raw)
            self.testid = match.group('gefid')
        except:
            pass
        try:
            match = re.search(testid_pattern, gef_raw)
            self.testid = match.group('testid')
        except:
            pass
        try:
            match = re.search(xydxdy_id_pattern, gef_raw)
            self.easting = float(match.group('X'))
            self.northing = float(match.group('Y'))
            self.srid = match.group('coordsys')
        except:
            pass
        try:
            match = re.search(xy_id_pattern, gef_raw)
            self.easting = float(match.group('X'))
            self.northing = float(match.group('Y'))
            self.srid = match.group('coordsys')
        except:
            pass

        # check oude RD-coördinaten
        if self.easting < 0:
            geometry = Point([self.easting, self.northing])
            reprojectedGeometry = gpd.GeoSeries(geometry, crs="epsg:28991").to_crs("epsg:28992")
            self.easting = reprojectedGeometry.x
            self.northing = reprojectedGeometry.y

        try:
            match = re.search(zdz_id_pattern, gef_raw)
            self.groundlevel = float(match.group('Z'))
        except:
            pass
        try:
            match = re.search(z_id_pattern, gef_raw)
            self.groundlevel = float(match.group('Z'))
        except:
            pass
        try:
            match = re.search(companyid_pattern, gef_raw)
            self.companyid = match.group('companyid')
        except:
            pass
        try:
            match = re.search(companyid_in_measurementext_pattern, gef_raw)
            self.companyid = match.group('companyid')
        except:
            pass
        try:
            match = re.search(projectid_pattern, gef_raw)
            self.projectid = match.group('projectid')
        except:
            pass
        try:
            match = re.search(projectname_pattern, gef_raw)
            self.projectname = match.group('projectname')
        except:
            pass
        try:
            match = re.search(projectname_in_measurementtext_pattern, gef_raw)
            self.projectname = match.group('projectname')
        except:
            pass
        try:
            match = re.search(startdate_pattern, gef_raw)
            startdatestring = match.group('startdate')
            startdatelist = [int(x) for x in startdatestring.split(',')]
            self.date = date(startdatelist[0], startdatelist[1], startdatelist[2])
        except:
            pass
        try:
            match = re.search(data_pattern, gef_raw)
            self.data = match.group('data')
        except:
            pass
        try:
            match = re.search(columnseparator_pattern, gef_raw)
            self.columnseparator = match.group('columnseparator')
        except:
            pass
        try:
            match = re.search(recordseparator_pattern, gef_raw)
            self.recordseparator = match.group('recordseparator')
        except:
            pass
        try:
            matches = re.finditer(columnvoid_pattern, gef_raw)
            for match in matches:
                columnnr = match.group('columnnr')
                voidvalue = match.group('voidvalue')
                self.columnvoid_values[int(columnnr) - 1] = float(voidvalue)
        except:
            pass
        try:
            # informatie in kolommen kan meerdere namen hebben
            # nummers zijn wel gestandardiseerd
            matches = re.finditer(columninfo_pattern, gef_raw)
            for match in matches:
                columnnr = match.group('columnnr')
                quantitynr = match.group('quantitynr')
                # kolomnummers in pandas starten op 0, in gef op 1 
                self.columninfo[int(columnnr) - 1] = GEF_COLINFO[quantitynr]
        except:
            pass

        # zet de data om in een dataframe, dan kunnen we er wat mee
        # TODO: read_fwf lijkt beter te werken dan csv voor sommige GEF, maar er zijn er ook met gedeclareerde separators, toch?
        # TODO: maar soms zijn de kolommen niet precies even breed, dan gaat het mis C:/Users/User/PBK/CPT/GEF/002488\002488_S01.GEF
#        self.data = pd.read_fwf(StringIO(self.data), header=None)         
        self.data = pd.read_csv(StringIO(self.data), sep=self.columnseparator, skipinitialspace=True, lineterminator='\n', header=None) 
        
        # vervang de dummy waarden door nan
        for columnnr, voidvalue in self.columnvoid_values.items():
            self.data[columnnr] = self.data[columnnr].replace(voidvalue, np.nan)
        # geef de kolommen andere namen
        self.data = self.data.rename(columns=self.columninfo)

        # soms is er geen wrijvingsgetal gerapporteerd
        if "frictionRatio" not in self.data.columns:
            # als er wel lokale wrijving is gerapporteerd, kan wrijvingsgetal berekend worden
            if "localFriction" in self.data.columns:
                self.data["frictionRatio"] = 100 * self.data["localFriction"] / self.data["coneResistance"]
            # anders is de waarde 0, ten behoeve van plot
            else:
                self.data["localFriction"] = 0
                self.data["frictionRatio"] = 0
        # soms is de ingelezen diepte positief en soms negatief
        # moet positief zijn 
        if "depth" in self.data.columns:
            self.data["depth"] = self.data["depth"].abs()

        self.check_depth()

        # nan waarden geven vervelende strepen in de afbeeldingen
        self.data.dropna(subset=["depth", "coneResistance", "localFriction", "frictionRatio"], inplace=True)

        # er komen soms negatieve waarden voor in coneResistance en frictionRatio, dat geeft vervelende strepen
        self.data = self.data[self.data["coneResistance"] >= 0]
        self.data = self.data[self.data["localFriction"] >= 0]
        self.data = self.data[self.data["frictionRatio"] >= 0]
        # frictionRatio kan ook heel groot zijn, dat geeft vervelende strepen
        self.data = self.data[self.data["frictionRatio"] <= 12]

        # lengte van sondering
        # gelijk aan finaldepth in xml
        self.finaldepth = self.data["depth"].max()

    def plot(self, path='./output'):
        if self.groundlevel == None:
            self.groundlevel = 0

        y = self.groundlevel - self.data["depth"]

        # x,y voor maaiveld in figuur
        x_maaiveld = [0, 10]
        y_maaiveld = [self.groundlevel, self.groundlevel]

        # figuur met conusweerstand, wrijving, wrijvingsgetal, helling en waterspanning
        # TODO: dit kunnen we ook op dezelfde manier doen als bij de boringen, zodat de verticale schaal altijd hetzelfde is
        # TODO: dat is wel lastiger met pdf maken

        colors = {'qc': 'red', 'fs': 'blue', 'Rf': 'green', 'inclination': 'grey', 'porepressure': 'black'}
        fig = plt.figure(figsize=(8.3 * 2,11.7 * 2)) # 8.3 x 11.7 inch is een A4
        gs = GridSpec(2, 1, height_ratios=[10,1])

        ax = fig.add_subplot(gs[0, 0])
        axes = [ax, ax.twiny(), ax.twiny()]

        # Rf plot vanaf rechts
        axes[2].invert_xaxis()  

        porePressures = ["porePressureU1", "porePressureU2", "porePressureU3"]
        for porePressure in porePressures:
            if porePressure in self.data.columns and not self.data[porePressure].isnull().all():
                axes.append(ax.twiny())
                axes[-1].plot(self.data[porePressure], y, label=porePressure[-2:], linewidth=1.25, color=colors['porepressure'], linestyle='-.')
                axes[-1].set_xlabel("u [Mpa]", loc='left')
                axes[-1].legend()
                axes[-1].set_xlim([-1, 1])
                axes[-1].spines['top'].set_position(('axes', 1.02))
                axes[-1].spines['top'].set_bounds(0,1)
                axes[-1].xaxis.label.set_color(colors['porepressure'])
                axes[-1].set_xticks([0,0.25,0.5,0.75,1.0])
                axes[-1].legend() 


        # maak een plot met helling, aan de rechterkant
        inclinations = ["inclinationEW", "inclinationNS", "inclinationX", "inclinationY", "inclinationResultant"]
        inclination_plots = 0
        for inclination in inclinations:
            if inclination in self.data.columns and not self.data[inclination].isnull().all():
                if inclination_plots == 0:
                    axes.append(ax.twiny())
                    axes[-1].invert_xaxis()
                    axes[-1].set_xlim([40, 0])
                    axes[-1].spines['top'].set_position(('axes', 1.02))
                    axes[-1].spines['top'].set_bounds(10,0)
                    axes[-1].set_xlabel("helling [deg]", loc='right')
                    axes[-1].xaxis.label.set_color(colors['inclination'])
                    axes[-1].set_xticks([0,2,4,6,8,10])
                axes[-1].plot(self.data[inclination], y, label=re.sub(r'inclination', '', inclination), linewidth=1.25, color=colors['inclination'])
                inclination_plots += 1
        if inclination_plots > 0:
            axes[-1].legend() 

        # plot data
        axes[0].plot(self.data['coneResistance'], y, label='qc [MPa]', linewidth=1.25, color=colors['qc'])
        axes[1].plot(self.data["localFriction"], y, label='fs [MPa]', linewidth=1.25, color=colors['fs'], linestyle='--')
        axes[2].plot(self.data["frictionRatio"], y, label='Rf [%]', linewidth=1.25, color=colors['Rf'])   

        # plot maaiveld, bestaat uit een streep en een arcering
        axes[0].plot(x_maaiveld, y_maaiveld, color='black')
        axes[0].barh(self.groundlevel, width=10, height=-0.4, align='edge', hatch='/\/', color='#ffffffff')

        # stel de teksten in voor de labels
        axes[0].set_ylabel("Niveau [m t.o.v. NAP]")
        axes[0].set_xlabel("qc [MPa]")
        axes[1].set_xlabel("fs [MPa]", loc='left')
        axes[2].set_xlabel("Rf [%]", loc='right')

        # verplaats de x-assen zodat ze niet overlappen       
        axes[1].spines['top'].set_bounds(0,1)
        axes[2].spines['top'].set_bounds(15,0)

        # kleur de labels van de x-assen hetzelfde als de data
        axes[0].xaxis.label.set_color(colors['qc'])
        axes[1].xaxis.label.set_color(colors['fs'])
        axes[2].xaxis.label.set_color(colors['Rf'])

        # stel de min en max waarden van de assen in
        axes[0].set_xlim([0, 40]) # conusweerstand
        axes[1].set_xlim([0, 2]) # plaatselijke wrijving 
        axes[2].set_xlim([40, 0]) # wrijvingsgetal
        
        axes[1].set_xticks([0,0.5,1.0])
        axes[2].set_xticks([0,2,4,6,8,10,12])

        # metadata in plot
        stempel = fig.add_subplot(gs[1, 0])
        stempel.set_axis_off()
        plt.text(0.05, 0.6, f'Sondering: {self.testid}\nx-coördinaat: {self.easting}\ny-coördinaat: {self.northing}\nmaaiveld: {self.groundlevel}\n', ha='left', va='top', fontsize=14, fontweight='bold')
        plt.text(0.35, 0.6, f'Uitvoerder: {self.companyid}\nDatum: {self.date}\nProjectnummer: {self.projectid}\nProjectnaam: {self.projectname}', ha='left', va='top', fontsize=14, fontweight='bold')
        plt.text(0.05, 0, 'Ingenieursbureau Gemeente Amsterdam - Team WGM - Vakgroep Geotechniek', fontsize=13.5)

        # maak het grid
        ax.minorticks_on()
        ax.tick_params(which='major', color='black')
        ax.tick_params(which='minor', color='black')
        ax.grid(which='major', linestyle='-', linewidth='0.15', color='black')
        ax.grid(which='minor', linestyle='-', linewidth='0.1')
        ax.grid(b=True, which='both')

        # sla de figuur op
        plt.tight_layout()
        plt.savefig(fname=f"./output/{self.filename}.png")
        plt.close('all')

        # andere optie voor bestandsnaam
        save_as_projectid_fromfile = False
        if save_as_projectid_fromfile:
            if self.projectid is not None: # TODO: dit moet ergens anders. Moet ook projectid uit mapid kunnen halen
                plt.savefig(fname=f"./output/{self.projectid}_{self.testid}.png")
                plt.close('all')
            elif self.projectname is not None:
                plt.savefig(fname=f"{path}/{self.projectname}_{self.testid}.png")
                plt.close('all')

    def check_depth(self):
        # soms is er geen diepte, maar wel sondeerlengte aanwezig
        # sondeerlengte als diepte gebruiken is goed genoeg als benadering
        # TODO: onderstaande blok voor diepte correctie is niet gecheckt op correctheid 
        if "depth" not in self.data.columns or self.data["depth"].isna().all():
            # verwijder de lege kolommen om het vervolg eenvoudiger te maken
            self.data.dropna(axis=1, how='all', inplace=True)
            # bereken diepte als inclinatie bepaald is
            if "penetrationLength" in self.data.columns:
                self.data.sort_values("penetrationLength", inplace=True)
                if "inclinationResultant" in self.data.columns:
                    self.data["correctedPenetrationLength"] = self.data["penetrationLength"].diff().abs() * np.cos(np.deg2rad(self.data["inclinationResultant"]))
                    self.data["depth"] = self.data["correctedPenetrationLength"].cumsum()                   
                elif "inclinationEW" in self.data.columns and "inclinationNS" in self.data.columns:
                    z = self.data["penetrationLength"].diff().abs()
                    x = z * np.tan(np.deg2rad(self.data["inclinationEW"]))
                    y = z * np.tan(np.deg2rad(self.data["inclinationNS"]))
                    self.data["inclinationResultant"] = np.rad2deg(np.cos(np.sqrt(x ** 2 + y ** 2 + z ** 2) / z))
                    self.data["correctedPenetrationLength"] = self.data["penetrationLength"].diff().abs() * np.cos(np.deg2rad(self.data["inclinationResultant"]))
                    self.data["depth"] = self.data["correctedPenetrationLength"].cumsum()
                elif "inclinationX" and "inclinationY" in self.data.columns:
                    z = self.data["penetrationLength"].diff().abs()
                    x = z * np.tan(np.deg2rad(self.data["inclinationX"]))
                    y = z * np.tan(np.deg2rad(self.data["inclinationY"]))
                    self.data["inclinationResultant"] = np.rad2deg(np.cos(np.sqrt(x ** 2 + y ** 2 + z ** 2) / z))
                    self.data["correctedPenetrationLength"] = self.data["penetrationLength"].diff().abs() * np.cos(np.deg2rad(self.data["inclinationResultant"]))
                    self.data["depth"] = self.data["correctedPenetrationLength"].cumsum()
                # anders is de diepte gelijk aan de penetration length
                else:
                    self.data["depth"] = self.data["penetrationLength"].abs()

@dataclass
class Bore():
    #TODO: uitbreiden voor BHR-P en BHR-G, deels werkt het al
    def __init__(self):
        self.projectid = None
        self.projectname = None
        self.companyid = None
        self.testid = None
        self.easting = None
        self.northing = None
        self.groundlevel = None
        self.srid = None
        self.testid = None
        self.date = None
        self.finaldepth = None
        self.soillayers = pd.DataFrame()
        self.metadata = {}
        self.descriptionquality = None

    def load_xml(self, xmlFile):
        # lees een boring in vanuit een BRO XML
        tree = ElementTree()
        tree.parse(xmlFile)
        root = tree.getroot()

        for element in root.iter():

            if 'broId' in element.tag or 'requestReference' in element.tag: # TODO: er zijn ook boringen zonder broId, met requestReference dat toevoegen levert een vreemde waarde voor testid
                self.testid = element.text

            if 'deliveredLocation' in element.tag:
                location = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                self.easting = float(location['pos'].split()[0])
                self.northing = float(location['pos'].split()[1])

            elif 'deliveredVerticalPosition' in element.tag:
                verticalPosition = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                self.groundlevel = float(verticalPosition['offset'])

            elif 'finalDepthBoring' in element.tag:
                self.finaldepth = float(element.text)

            elif 'descriptionReportDate' in element.tag:
                date = {re.sub(r'{.*}', '', p.tag) : re.sub(r'\n\s*', '', p.text) for p in element.iter() if p.text is not None}
                self.date = datetime.strptime(date['date'], '%Y-%m-%d')
            
            elif 'descriptionQuality' in element.tag:
                self.descriptionquality = element.text

            elif 'layer' in element.tag:
                self.soillayers.append({re.sub(r'{.*}', '', p.tag) : re.sub(r'\s*', '', p.text) for p in element.iter() if p.text is not None})

        self.metadata = {"easting": self.easting, "northing": self.northing, "groundlevel": self.groundlevel, "testid": self.testid, "date": self.date, "finaldepth": self.finaldepth}

        # zet om in een dataframe om het makkelijker te verwerken
        self.soillayers = pd.DataFrame(self.soillayers)
        
        self.soillayers = self.add_components(self)

        # specialMaterial was voor het maken van de componenten op NBE gezet, nu weer terug naar de oorspronkelijke waarde
        if "specialMaterial" in self.soillayers.columns:
            self.soillayers["soilName"][self.soillayers["soilName"] == "NBE"] = self.soillayers["specialMaterial"]
        
        # voeg kolommen toe met absolute niveaus (t.o.v. NAP)
        self.soillayers["upperBoundary"] = pd.to_numeric(self.soillayers["upperBoundary"])
        self.soillayers["lowerBoundary"] = pd.to_numeric(self.soillayers["lowerBoundary"])

        self.soillayers["upper_NAP"] = self.groundlevel - self.soillayers["upperBoundary"] 
        self.soillayers["lower_NAP"] = self.groundlevel - self.soillayers["lowerBoundary"] 

    def load_gef(self, gefFile):

        self.columninfo = {}
        self.columnvoid_values = {}
        self.descriptionquality = str() # TODO

        GEF_COLINFO = { 
            '1': 'upper',
            '2': 'lower'
        }

        test_id_pattern = re.compile(r'#TESTID\s*=\s*(?P<testid>.*)\s*')
        xy_id_pattern = re.compile(r'#XYID\s*=\s*(?P<refsystem>\d*),\s*(?P<X>\d*\.?\d*),\s*(?P<Y>\d*\.?\d*)(,\s*(?P<dX>\d*\.?\d*),\s*(?P<dY>\d*\.?\d*))?\s*')
        xydxdy_id_pattern = re.compile(r'#XYID\s*=\s*(?P<coordsys>\d*)\s*,\s*(?P<X>\d*.?\d*)\s*,\s*(?P<Y>\d*.?\d*)\s*,\s*(?P<dx>\d*.?\d*),\s*(?P<dy>\d*.?\d*)\s*')
        z_id_pattern = re.compile(r'#ZID\s*=\s*(?P<refsystem>\d*),\s*(?P<Z>\d*\.?\d*)(,\s*(?P<dZ>\d*\.?\d*))')
        zdz_id_pattern = re.compile(r'#ZID\s*=\s*(?P<datum>\d*)\s*,\s*(?P<Z>.*)\s*,\s*(?P<dZ>.*)\s*')

        companyid_pattern = re.compile(r'#COMPANYID\s*=\s*(?P<companyid>.*),\s*\w*,\s*\d*\s*')
        projectid_pattern = re.compile(r'#PROJECTID\s*=\s*(?P<projectid>\d*)\s*')
        projectname_pattern = re.compile(r'#PROJECTNAME\s*=\s*(?P<projectname>.*)\s*')
        companyid_in_measurementext_pattern = re.compile(r'#MEASUREMENTTEXT\s*=\s*\d*,\s*(?P<companyid>.*),\s*boorbedrijf\s*')
        projectname_in_measurementtext_pattern = re.compile(r'#MEASUREMENTTEXT\s*=\s*\d*,\s*(?P<projectname>.*),\s*projectnaam\s*')
        filedate_pattern = re.compile(r'#FILEDATE\s*=\s*(?P<filedate>\d*,\s*\d*,\s*\d*)\s*')

        data_pattern = re.compile(r'#EOH\s*=\s*(?P<data>(.*\n)*)')

        columnvoid_pattern = re.compile(r'#COLUMNVOID\s*=\s*(?P<columnnr>\d*),\s*(?P<voidvalue>.*)\s*')
        columninfo_pattern = re.compile(r'#COLUMNINFO\s*=\s*(?P<columnnr>\d*),\s*(?P<unit>.*),\s*(?P<parameter>.*),\s*(?P<quantitynr>\d*)\s*')
        columnseparator_pattern = re.compile(r'#COLUMNSEPARATOR\s*=\s*(?P<columnseparator>.*)')
        recordseparator_pattern = re.compile(r'#RECORDSEPARATOR\s*=\s*(?P<recordseparator>.*)')

        with open(gefFile) as f:
            gef_raw = f.read()

        try:
            match = re.search(test_id_pattern, gef_raw)
            self.testid = match.group('testid')
        except:
            pass

        try:
            match = re.search(xy_id_pattern, gef_raw)
            self.easting = float(match.group('X'))
            self.northing = float(match.group('Y'))
        except:
            pass
        try:
            match = re.search(xydxdy_id_pattern, gef_raw)
            self.easting = float(match.group('X'))
            self.northing = float(match.group('Y'))
        except:
            pass

        # check oude RD-coördinaten
        if self.easting < 0:
            geometry = Point([self.easting, self.northing])
            reprojectedGeometry = gpd.GeoSeries(geometry, crs="epsg:28991").to_crs("epsg:28992")
            self.easting = reprojectedGeometry.x
            self.northing = reprojectedGeometry.y

        try:
            match = re.search(z_id_pattern, gef_raw)
            self.groundlevel = float(match.group('Z'))
        except:
            pass
        try:
            match = re.search(zdz_id_pattern, gef_raw)
            self.groundlevel = float(match.group('Z'))
        except:
            pass
        try:
            match = re.search(data_pattern, gef_raw)
            self.soillayers = match.group('data')
        except:
            pass

        try:
            match = re.search(companyid_pattern, gef_raw)
            self.companyid = match.group('companyid')
        except:
            pass
        try:
            match = re.search(projectid_pattern, gef_raw)
            self.projectid = match.group('projectid')
        except:
            pass
        try:
            match = re.search(projectname_pattern, gef_raw)
            self.projectname = match.group('projectname')
        except:
            pass
        try:
            match = re.search(companyid_in_measurementext_pattern, gef_raw)
            self.companyid = match.group('companyid')
        except:
            pass
        try:
            match = re.search(projectname_in_measurementtext_pattern, gef_raw)
            self.projectname = match.group('projectname')
        except:
            pass
        try:
            match = re.search(filedate_pattern, gef_raw)
            filedatestring = match.group('filedate')
            filedatelist = [int(x) for x in filedatestring.split(',')]
            self.date = date(filedatelist[0], filedatelist[1], filedatelist[2])
        except:
            pass
        try:
            match = re.search(columnseparator_pattern, gef_raw)
            self.columnseparator = match.group('columnseparator')
        except:
            pass
        try:
            match = re.search(recordseparator_pattern, gef_raw)
            self.recordseparator = match.group('recordseparator')
        except:
            pass
        try:
            matches = re.finditer(columnvoid_pattern, gef_raw)
            for match in matches:
                columnnr = match.group('columnnr')
                voidvalue = match.group('voidvalue')
                self.columnvoid_values[int(columnnr) - 1] = float(voidvalue)
        except:
            pass
        try:
            # informatie in kolommen kan meerdere namen hebben
            # nummers zijn wel gestandardiseerd
            matches = re.finditer(columninfo_pattern, gef_raw)
            for match in matches:
                columnnr = match.group('columnnr')
                quantitynr = match.group('quantitynr')
                # kolomnummers in pandas starten op 0, in gef op 1 
                self.columninfo[int(columnnr) - 1] = GEF_COLINFO[quantitynr]
        except:
            pass
        
        # zet de data om in een dataframe, dan kunnen we er wat mee    
        self.soillayers = pd.read_csv(StringIO(self.soillayers), sep=self.columnseparator, skipinitialspace=True, header=None)
        
        # vervang de dummy waarden door nan
        for columnnr, voidvalue in self.columnvoid_values.items():
            self.soillayers[columnnr] = self.soillayers[columnnr].replace(voidvalue, np.nan)

        # TODO: deze namen kloppen wellicht niet helemaal
        self.columninfo[max(self.columninfo.keys()) + 1] = 'soilName'
        self.columninfo[max(self.columninfo.keys()) + 1] = 'toelichting'
        self.columninfo[max(self.columninfo.keys()) + 1] = 'materialproperties'

        # geef de kolommen andere namen
        self.soillayers = self.soillayers.rename(columns=self.columninfo)

        self.soillayers = self.soillayers.replace("'", "", regex=True)

        # voeg niveaus t.o.v. NAP toe
        self.soillayers["upper_NAP"] = self.groundlevel - self.soillayers["upper"] 
        self.soillayers["lower_NAP"] = self.groundlevel - self.soillayers["lower"] 

        # geef de maximaal diepte t.o.v. maaiveld
        self.finaldepth = self.soillayers["upper_NAP"].max() - self.soillayers["lower_NAP"].min()

        # zet de codering om in iets dat geplot kan worden
        material_pattern = re.compile(r'(?P<main>[GKLSVZ])(?P<second>[ghklsvz])?(?P<secondQuantity>\d)?(?P<third>[ghklsvz])?(?P<thirdQuantity>\d)?(?P<fourth>[ghklsvz])?(?P<fourthQuantity>\d)?')

        components = []
        for row in self.soillayers.itertuples():
            componentsRow = {}
            material = str(getattr(row, 'soilName')) # kreeg een keer 0 als material, vandaar de str
            if 'NBE' in material or '0' in material:
                main = 'N'
                secondQuantity, thirdQuantity, fourthQuantity = 0, 0, 0
            else:
                match = re.search(material_pattern, material)
                main = match.group('main')

            try:
                match = re.search(material_pattern, material)
                second = match.group('second')
                secondQuantity = 0.05
            except:
                pass

            try:
                match = re.search(material_pattern, material)
                third = match.group('third')
                thirdQuantity = 0.
            except:
                pass

            try:
                match = re.search(material_pattern, material)
                fourth = match.group('fourth')
                fourthQuantity = 0.
            except:
                pass

            try:
                match = re.search(material_pattern, material)
                secondQuantity = int(match.group('secondQuantity')) * 0.05
            except:
                pass

            try:
                match = re.search(material_pattern, material)
                thirdQuantity = int(match.group('thirdQuantity')) * 0.049
            except:
                pass

            try:
                match = re.search(material_pattern, material)
                fourthQuantity = int(match.group('fourthQuantity')) * 0.048
            except:
                pass

            mainQuantity = 1 - secondQuantity - thirdQuantity - fourthQuantity

            material_components = {"G": 0, "Z": 1, "K": 2, "S": 5, "V": 4, "L": 3, "H": 4, "N": 6}

            componentsRow[mainQuantity] = material_components[main]
            try:
                componentsRow[secondQuantity] = material_components[second.upper()]
            except:
                pass
            try:
                componentsRow[thirdQuantity] = material_components[third.upper()]
            except:
                pass

            try:
                componentsRow[fourthQuantity] = material_components[fourth.upper()]
            except:
                pass

            components.append(componentsRow)
        self.soillayers["components"] = components


    def plot(self, path='./output'):
        # maak een eenvoudige plot van een boring
        uppers = list(self.soillayers["upper_NAP"])
        lowers = list(self.soillayers["lower_NAP"])

        # maak een diagram met primaire en secundaire componenten
        fig = plt.figure(figsize=(6, self.finaldepth + 2)) 
        gs = GridSpec(2, 2, height_ratios=[self.finaldepth, 2], width_ratios=[2, 1] , figure=fig)
        
        axes = []
        axes.append(fig.add_subplot(gs[0, 0]))
        axes.append(fig.add_subplot(gs[0, 1], sharey=axes[0]))
        axes.append(fig.add_subplot(gs[1,:]))

        components = list(self.soillayers["components"])
        colorsDict = {0: "orange", 1: "yellow", 4: "brown", 2: "steelblue", 0: "gray", 5: "lime", 3: "purple", 6: "black"}
        hatchesDict = {1: "...", 4: "---", 2: "///", 0: "ooo", 5: "\\\\\\", 3:"", 6: ""}
        for upper, lower, component in reversed(list(zip(uppers, lowers, components))):
            left = 0
            for comp, nr in component.items():
                barPlot = axes[0].barh(lower, width=comp, left=left, height=upper-lower, color=colorsDict[nr], hatch=hatchesDict[nr], edgecolor="black", align="edge")
                left += comp

        axes[0].set_ylim([self.groundlevel - self.finaldepth, self.groundlevel])
        axes[0].set_xticks([])
        axes[0].set_ylabel('diepte [m t.o.v. NAP]')

        # voeg de beschrijving toe
        for layer in self.soillayers.itertuples():
            y = (getattr(layer, "lower_NAP") + getattr(layer, "upper_NAP")) / 2
            propertiesText = ""
            for materialproperty in ['tertiaryConstituent', 'colour', 'dispersedInhomogeneity', 'carbonateContentClass',
                                        'organicMatterContentClass', 'mixed', 'sandMedianClass', 'grainshape',
                                        'sizeFraction', 'angularity', 'sphericity', 'fineSoilConsistency',
                                        'organicSoilTexture', 'organicSoilConsistency', 'peatTensileStrength']:
                # TODO: dit werkt nog niet goed
                if materialproperty in self.soillayers.columns:
                    value = getattr(layer, materialproperty)
                    try:
                        np.isnan(value)
                    except:
                        propertiesText += f', {value}'
            text = f'{getattr(layer, "soilName")}{propertiesText}'
            axes[1].text(0, y, text, wrap=True)


        # verberg de assen van de onderste plot en rechtse plot zodat deze gebruikt kunnen worden voor tekst
        axes[1].set_axis_off()
        axes[2].set_axis_off()
        plt.text(0.05, 0.6, f'Boring: {self.testid}\nx-coördinaat: {self.easting}\ny-coördinaat: {self.northing}\nmaaiveld: {self.groundlevel}\nkwaliteit: {self.descriptionquality}\ndatum: {self.date}', fontsize=14, fontweight='bold')
        plt.text(0.05, 0.2, 'Ingenieursbureau Gemeente Amsterdam Vakgroep Geotechniek Python ', fontsize=10)
        plt.tight_layout()
        plt.savefig(fname=f'{path}/{self.testid}.png')
        plt.close('all')

    def interpret_qc_only(self, cpt):
        # DFoundations qc only rule
        conditionsQcOnly = [
            cpt.data['coneResistance'] > 4,
            cpt.data['coneResistance'] > 1,
            cpt.data['coneResistance'] > 0.1
        ]
        choicesQcOnly = ['zand', 'klei', 'veen']
        cpt.data['qcOnly'] = np.select(conditionsQcOnly, choicesQcOnly, np.nan)
        return cpt.data

    def interpret_three_type(self, cpt, is_below):
        # DFoundations 3 type rule [frictionRatio, coneResistance] waarden voor lijn die bovengrens vormt
        soils3Type = OrderedDict([
            ['veen', [np.full((len(cpt.data), 2), [0., np.log10(0.00002)]), np.full((len(cpt.data), 2), [10, np.log10(0.2)])]],
            ['klei', [np.full((len(cpt.data), 2), [0., np.log10(0.01)]), np.full((len(cpt.data), 2), [10, np.log10(100)])]],
            ['zand', [np.full((len(cpt.data), 2), [0., np.log10(0.5)]), np.full((len(cpt.data), 2), [10, np.log10(5000)])]]
            ])
        # conditions: check of punt onder de bovengrens ligt
        conditions3Type = [
            is_below(cpt.data[['frictionRatio', 'logConeResistance']], value[0], value[1]) for value in soils3Type.values()
            ]
        choices3Type = soils3Type.keys()
        # toewijzen materialen op basis van de conditions
        cpt.data['threeType'] = np.select(conditions3Type, choices3Type, None)
        return cpt.data
    
    def interpret_nen(self, cpt, is_below):
        # DFoundations NEN rule [frictionRatio, coneResistance]
        soilsNEN = OrderedDict([
            #['veen', [[0, np.log10(0)], [10, np.log10(0.08)]]], # slappe consistentie, past niet in schema
            ['veen', [[0, np.log10(0.000058)], [10, np.log10(.58)]]], # coneResistance van het eerste punt aangepast 
            #['humeuzeKlei', [[0, np.log10(0.004)], [10, np.log10(39.59)]]], # slappe consistentie, past niet in schema
            ['humeuzeKlei', [[0, np.log10(0.02)], [10, np.log10(201)]]], 
            ['klei', [[0, np.log10(0.068)], [10, np.log10(676.1)]]],
            ['zwakZandigeKlei', [[0, np.log10(0.292)], [10, np.log10(2921)]]],
            ['sterkZandigeKlei', [[0, np.log10(0.516)], [10, np.log10(5165)]]],
            ['zwakZandigSilt', [[0, np.log10(1.124)], [10, np.log10(11240)]]],
            ['sterkZandigSilt', [[0, np.log10(2.498)], [10, np.log10(24980)]]],
            ['sterkSiltigZand', [[0, np.log10(4.606)], [10, np.log10(46060)]]],
            ['zwakSiltigZand', [[0, np.log10(8.594)], [10, np.log10(85940)]]],
            ['zand', [[0, np.log10(13.11)], [10, np.log10(131100)]]],
            ['grind', [[0, np.log10(24.92)], [10, np.log10(249200)]]]
            ])
        
        conditionsNEN = [
            is_below(cpt.data[['frictionRatio', 'logConeResistance']], np.full((len(cpt.data), 2),value[0]), np.full((len(cpt.data), 2),value[1])) for value in soilsNEN.values()
            ]
        choicesNEN = soilsNEN.keys()
        cpt.data['NEN'] = np.select(conditionsNEN, choicesNEN, None)
        return cpt.data

    def from_cpt(self, cpt):
        #TODO: functies voor de  interpretaties passen wellicht beter bij de Cpt class

        # functie die later gebruikt wordt
        is_below = lambda p,a,b: np.cross(p-a, b-a) > 0
        
        # de threeType en NEN regels gelden voor log(qc)
        cpt.data['logConeResistance'] = np.log(cpt.data['coneResistance'])

        cpt.data = self.interpret_qc_only(cpt)
        cpt.data = self.interpret_three_type(cpt, is_below)
        cpt.data = self.interpret_nen(cpt, is_below)


        # maak een object alsof het een boring is
        self.soillayers['geotechnicalSoilName'] = cpt.data['threeType']
        # TODO frictionRatio en coneResistance horen er eigenlijk niet in thuis, maar zijn handig als referentie
        self.soillayers[['frictionRatio', 'coneResistance']] = cpt.data[['frictionRatio', 'coneResistance']]
        self.groundlevel = cpt.groundlevel
        self.finaldepth = cpt.data['depth'].max()
        self.descriptionquality = 'cpt'
        self.testid = cpt.testid
        self.easting = cpt.easting
        self.northing = cpt.northing
        self.soillayers = self.add_components()

        # verwijder de lagen met hetzelfde materiaal
        self.soillayers = self.soillayers[self.soillayers['geotechnicalSoilName'].ne(self.soillayers['geotechnicalSoilName'].shift(1))]

        # voeg de laatste regel weer toe
        lastrow = self.soillayers.iloc[-1]
        self.soillayers.append(lastrow)

        # vul de regels die buiten de schaal vallen met wat er boven zit
        self.soillayers['geotechnicalSoilName'].fillna(method='ffill', inplace=True)

        # voeg laaggrenzen toe        
        self.soillayers['upper_NAP'] = cpt.groundlevel - cpt.data['depth']
        self.soillayers['lower_NAP'] = self.soillayers['upper_NAP'].shift(-1)
        # voeg de onderkant van de onderste laag toe
        self.soillayers.loc[self.soillayers.index.max(), 'lower_NAP'] = cpt.groundlevel - self.finaldepth
        
        self.soillayers.dropna(inplace=True)

    def add_components(self):
        # voeg verdeling componenten toe
        # van https://github.com/cemsbv/pygef/blob/master/pygef/broxml.py
        material_components = ["gravel_component", "sand_component", "clay_component", "loam_component", "peat_component", "silt_component"]
        soil_names_dict_lists = {
            "betonOngebroken": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],  # specialMaterial
            "grind":  [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "humeuzeKlei": [0.0, 0.0, 0.9, 0.0, 0.1, 0.0],
            "keitjes": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "klei": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            "kleiigVeen": [0.0, 0.0, 0.3, 0.0, 0.7, 0.0],
            "kleiigZand": [0.0, 0.7, 0.3, 0.0, 0.0, 0.0],
            "kleiigZandMetGrind": [0.05, 0.65, 0.3, 0.0, 0.0, 0.0],
            "NBE": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0], # specialMaterial
            "puin": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],  # specialMaterial
            "siltigZand": [0.0, 0.7, 0.0, 0.0, 0.0, 0.3],
            "siltigZandMetGrind": [0.05, 0.65, 0.0, 0.0, 0.0, 0.3],
            "sterkGrindigZand": [0.3, 0.7, 0.0, 0.0, 0.0, 0.0],
            "sterkGrindigeKlei": [0.3, 0.0, 0.7, 0.0, 0.0, 0.0],
            "sterkSiltigZand": [0.0, 0.7, 0.0, 0.0, 0.0, 0.3],
            "sterkZandigGrind": [0.7, 0.3, 0.0, 0.0, 0.0, 0.0],
            "sterkZandigSilt": [0.0, 0.3, 0.0, 0.0, 0.0, 0.7],
            "sterkZandigeKlei": [0.0, 0.3, 0.7, 0.0, 0.0, 0.0],
            "sterkZandigeKleiMetGrind": [0.05, 0.3, 0.65, 0.0, 0.0, 0.0],
            "sterkZandigVeen": [0.0, 0.3, 0.0, 0.0, 0.7, 0.0],
            "veen": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "zand": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            "zwakGrindigZand": [0.1, 0.9, 0.0, 0.0, 0.0, 0.0],
            "zwakGrindigeKlei": [0.1, 0.0, 0.9, 0.0, 0.0, 0.0],
            "zwakSiltigZand": [0.0, 0.9, 0.0, 0.0, 0.0, 0.1],
            "zwakSiltigeKlei": [0.0, 0.0, 0.9, 0.0, 0.0, 0.1],
            "zwakZandigGrind": [0.9, 0.1, 0.0, 0.0, 0.0, 0.0],
            "zwakZandigSilt": [0.0, 0.9, 0.0, 0.0, 0.0, 0.1],
            "zwakZandigVeen": [0.0, 0.1, 0.0, 0.0, 0.9, 0.0],
            "zwakZandigeKlei": [0.0, 0.1, 0.9, 0.0, 0.0, 0.0],
            "zwakZandigeKleiMetGrind": [0.05, 0.1, 0.85, 0.0, 0.0, 0.0],
        }

        # voor sorteren op bijdrage is het handiger om een dictionary te maken
        soil_names_dict_dicts = {}
        for key, value in soil_names_dict_lists.items():
            soil_names_dict_dicts[key] = dict(sorted({v: i for i, v in enumerate(value)}.items(), reverse=True))

        # TODO: soilNameNEN5104 specialMaterial
        self.soillayers["soilName"] = np.where(self.soillayers["geotechnicalSoilName"].isna(), "NBE", self.soillayers["geotechnicalSoilName"])
        # voeg de componenten toe
        self.soillayers["components"] = self.soillayers["soilName"].map(soil_names_dict_dicts)
        return self.soillayers