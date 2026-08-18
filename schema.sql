PRAGMA foreign_keys = ON;

--Item Group
CREATE TABLE IF NOT EXISTS IGP (

    ITMGRP TEXT PRIMARY KEY,			--Item Group ID
    ISACTIVE INTEGER				--Is Active Bool

);

--Color lookup Table
CREATE TABLE IF NOT EXISTS COLOR (
    COLOR TEXT PRIMARY KEY,			--Color Name
    CHEX TEXT,					--Color Hex Code
    ISACTIVE INTEGER				--Is Active Bool
);

--Glass Texture Lookup Table
CREATE TABLE IF NOT EXISTS GTL (

    GLSTEX TEXT PRIMARY KEY,			--Glass texture name
    ISACTIVE INTEGER				--Is Active Bool

);

--Glass Source
CREATE TABLE IF NOT EXISTS GSL (

    GLSOURCE TEXT PRIMARY KEY,			--Glass Source Name
    SRCWEB INTEGER,				--Web link URL
    GLSLOGO TEXT,				--Source Logo
    GLSNOTE TEXT,				--Notes about source
    ISACTIVE INTEGER				--Is Active Bool

);

--Units Lookup Table
CREATE TABLE IF NOT EXISTS UNTS (
    UNTTYPE TEXT PRIMARY KEY,			--Unit Type 
    CFACTOR NUMERIC				--Conversion Factor

);

--Patina Lookup Table
CREATE TABLE IF NOT EXISTS PATINA (
    PATINA TEXT PRIMARY KEY			--Name of Patina
);

--Glass Transparency Lookup Table
CREATE TABLE IF NOT EXISTS GTRNS (

    GTRNSN TEXT PRIMARY KEY,			--Transparency Name
    GTRNSV INTEGER				--Transparency Value
);


--Vendor Group
CREATE TABLE IF NOT EXISTS VGP (

    VENGRP TEXT PRIMARY KEY,			--Vendor Group Name
    ISACTIVE INTEGER				--Is Active Bool

);

--Venue information
CREATE TABLE IF NOT EXISTS VENUE (

    VENUEID INTEGER PRIMARY KEY AUTOINCREMENT,	--Auto Venue ID
    VENNAME TEXT,				--Venue Name
    VENGRP TEXT,				--Venue Group
    VENNOTE TEXT,				--Notes about Venue
    VENLOGO TEXT,				--Logo of Venue
    VENIMG TEXT,				--Image of Venue
    VSTREET1 TEXT,				--Venue Address 1
    VSTREET2 TEXT,				--Venue Address 2
    VCITY TEXT,					--Venue City
    VSTATE TEXT,				--Venue State
    VZIP TEXT,					--Venue Zip Code
    VURL TEXT,					--URL to Venue page
    VINSTA TEXT,				--Link to Venue Instagram
    VFB TEXT,					--Link to Venue Facebook
    VCONNAME TEXT,				--Venue Contact Name
    VCONPHN TEXT,				--Venue Contact Phone number
    VCONEMAIL TEXT,				--Venue Contact E-mail
    VCONNOTE TEXT,				--Notes about Venue Contact
    VENDLINE TEXT,				--Venue Application Deadline
    VCAMPAVA INTEGER,				--Venue Camping Avalibility Bool
    VCAMPED INTEGER,				--Venue Camped at location Bool
    VCAMPFEE NUMERIC,				--Venue Camping Fee
    VCAMPNT TEXT,				--Venue Camping Notes
    VFEES NUMERIC,				--Venue Vendor Fees
    VFEENOTE TEXT,				--Venue Fee Notes
    VENUELOC TEXT,				--Venue Additional Location Information
    VMULTI INTEGER,				--Venue Multi Weekend Boolean
    VSDATE TEXT,				--Venue Start Date
    VEDATE TEXT,				--Venue End Date
    VM INTEGER, VMST TEXT, VMET TEXT,		--Venue Monday Boolean, Monday Start Time, Monday End time
    VTE INTEGER, VTST TEXT, VTET TEXT,		--Venue Tuesday Boolean, Tuesday Start Time, Tuesday End time
    VW INTEGER, VWST TEXT, VWET TEXT,		--Venue Wednesday Boolean, Wednesday Start Time, Wednesday End time
    VR INTEGER, VRST TEXT, VRET TEXT,		--Venue Thursday Boolean, Thursday Start Time, Thursday End time
    VF INTEGER, VFST TEXT, VFET TEXT,		--Venue Friday Boolean, Friday Start Time, Friday End time
    VST INTEGER, VSTST TEXT, VSTET TEXT,	--Venue Satday Boolean, Satday Start Time, Satday End time
    VSN INTEGER, VSNST TEXT, VSNET TEXT,	--Venue Sunday Boolean, Sunday Start Time, Sunday End time
    ISACTIVE INTEGER,				--Is Active Boolean

    FOREIGN KEY (VENGRP) REFERENCES VGP(VENGRP) ON DELETE SET NULL ON UPDATE CASCADE


);

--Audit Table
CREATE TABLE IF NOT EXISTS AUDIT (

    TRANSID INTEGER PRIMARY KEY AUTOINCREMENT,	--Transaction ID
    TRNOP TEXT CHECK(TRNOP IN ('INSERT', 'UPDATE', 'DELETE')), --Transaction Type
    TRNOLD TEXT,				--Old Value
    TRNNEW TEXT,				--New Value
    TRNCOL TEXT,				--Transaction Column
    TRNTBL TEXT,				--Transaction Table
    TRNTS TEXT DEFAULT CURRENT_TIMESTAMP	--Transaction Time Stamp

);


--Glass Item
CREATE TABLE IF NOT EXISTS GSI (

    GLASSID INTEGER PRIMARY KEY AUTOINCREMENT,	--Glass Id number
    GLSNAME TEXT,				--Glass Name
    GLSMANF TEXT,				--Glass Manufacturer
    GLSLEN NUMERIC,				--Glass Length
    GLSWID NUMERIC,				--Glass Width
    GLSTHK NUMERIC,				--Glass Thickness
    GLSTEX TEXT,				--Glass Texture
    GLSIRI INTEGER,				--Iridescent Bool
    GLSOPAL INTEGER,				--Opalescent Bool
    GLSOURCE TEXT,				--Glass Source
    GLLINK TEXT,				--URL to Glass
    GLSIMG TEXT,				--Image of Glass
    GLSNOTE TEXT,				--Notes about Glass
    COLOR TEXT,					--Glass color
    GTRNSN TEXT,				--Glass Transparency
    ISACTIVE INTEGER,				--Is Active Bool

    FOREIGN KEY (GLSTEX) REFERENCES GTL(GLSTEX) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (COLOR) REFERENCES COLOR(COLOR) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (GLSOURCE) REFERENCES GSL(GLSOURCE) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (GTRNSN) REFERENCES GTRNS(GTRNSN) ON DELETE SET NULL ON UPDATE CASCADE

);

--Misc Materal Type Lookup Table
CREATE TABLE IF NOT EXISTS MST (
    MSITYPE TEXT PRIMARY KEY			--Misc Item Type
);

--Misc Item
CREATE TABLE IF NOT EXISTS MSI (

    MSIID INTEGER PRIMARY KEY AUTOINCREMENT,	--Misc Item ID
    MSINAME TEXT,				--Misc Item Name
    MSIIMG TEXT,				--Misc Item Image
    MSISTOCK INTEGER,				--Misc Item Stock
    MSIURL TEXT,				--Misc Item URL
    MSINOTE TEXT,				--Misc Item Notes
    MSIUNIT NUMERIC,				--Misc Item Units per Item
    UNTTYPE TEXT,				--Misc Item Unit Type
    MSITYPE TEXT,				--Misc Item Category Type
    ISACTIVE INTEGER,				--Is Active Bool

    FOREIGN KEY (MSITYPE) REFERENCES MST(MSITYPE) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (UNTTYPE) REFERENCES UNTS(UNTTYPE) ON DELETE CASCADE ON UPDATE CASCADE
    
);

--Item to Misc Item Link
CREATE TABLE IF NOT EXISTS IMI (
    IMIID INTEGER PRIMARY KEY AUTOINCREMENT,	--IMI Link ID
    ITEMID INTEGER,				--Item ID
    MSIID INTEGER,				--Misc Item ID
    IMIAMT NUMERIC,				--Amount of Misc Item

    FOREIGN KEY (MSIID) REFERENCES MSI(MSIID) ON DELETE CASCADE ON UPDATE CASCADE
);

--Items
CREATE TABLE IF NOT EXISTS ITM (

    ITEMID INTEGER PRIMARY KEY AUTOINCREMENT,	--Item ID
    ITMNAME TEXT,				--Item Name
    ITMIMG TEXT,				--Item Image
    ONEOFF INTEGER,				--One off Item
    VARIAT INTEGER,				--Is Variation Boolean
    ITMGRP TEXT,				--Item Group
    CURRENT INTEGER,				--Currently Being Sold Bool
    ITMPTRN TEXT,				--Item Pattern Image
    ITMSVG TEXT,				--Item SVG
    ITMNOTE TEXT,				--Item Notes
    ITMLEN TEXT,				--Item Length
    ITMWID TEXT,				--Item Width
    IMISLDR INTEGER,				--Item Solder IMI ID
    IMICAME INTEGER,				--Item CAME IMI ID
    IMIFOIL INTEGER,				--Item Foil IMI ID
    IMICHAIN INTEGER,				--Item Chain IMI ID
    IMIRING INTEGER,				--Item Ring IMI ID
    IMIWIRE INTEGER,				--Item Wire IMI ID
    PARENT INTEGER,				--Parent Item ID
    PATINA TEXT,				--Patina Type
    ISACTIVE INTEGER,				--Is Active Item

    FOREIGN KEY (ITMGRP) REFERENCES IGP(ITMGRP) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMISLDR) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMICAME) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMIFOIL) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMICHAIN) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMIRING) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (IMIWIRE) REFERENCES IMI(IMIID) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (PATINA) REFERENCES PATINA(PATINA) ON DELETE SET NULL ON UPDATE CASCADE
);

--Misc Item Price
CREATE TABLE IF NOT EXISTS MSP (
    MSIID INTEGER,				--Misc Item ID 
    MSIPRICE NUMERIC,                         	--Misc Item Price
    STDATE TEXT,                              	--Price Start Date
    ENDDATE TEXT,                             	--Price End Date

    FOREIGN KEY (MSIID) REFERENCES MSI(MSIID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Item Price
CREATE TABLE IF NOT EXISTS IPC (
    ITEMID INTEGER,                           	--Item ID
    ITMPRICE NUMERIC,                         	--Item Price
    STDATE TEXT,                              	--Start Date
    ENDDATE TEXT,                             	--End Date

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Glass Price
CREATE TABLE IF NOT EXISTS GPC (

    GLASSID INTEGER,                          	--Glass ID
    GLSPRICE NUMERIC,                         	--Glass Price
    STDATE TEXT,                              	--Start Date
    ENDDATE TEXT,                             	--End Date

    FOREIGN KEY (GLASSID) REFERENCES GSI(GLASSID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Item Glass Components
CREATE TABLE IF NOT EXISTS IGC (

    COMPID INTEGER PRIMARY KEY AUTOINCREMENT,	--Component ID
    COMPNAME TEXT,				--Component Name (opt)
    ITEMID INTEGER,				--Item ID
    COMPNUM INTEGER,				--Component Number
    SVGREG INTEGER,				--SVG Region Number
    GLASSID INTEGER,				--Glass ID
    COMPLEN NUMERIC,				--Component Length
    COMPWID NUMERIC,				--Component Width
    COMPNOTE TEXT,				--Component Note
    ISSCRAP INTEGER,				--Can be made from scraps bool
    ISGRAIN INTEGER,				--Pay attention to Grain bool
    ISACTIVE INTEGER,				--Is Active bool

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (GLASSID) REFERENCES GSI(GLASSID) ON DELETE SET NULL ON UPDATE CASCADE
);

--Item Current State
CREATE TABLE IF NOT EXISTS ICC (

    IPID INTEGER PRIMARY KEY AUTOINCREMENT,	--Item State ID
    ITEMID INTEGER,				--Item ID
    IPCUT INTEGER,				--Item num in Cut State
    IPGRND INTEGER,				--Item num in Grind State
    IPWASH INTEGER,				--Item num in Wash State
    IPFOIL INTEGER,				--Item num in Foil State
    IPSLDR INTEGER,				--Item num in Solder State
    IPPOLISH INTEGER,				--Item num in Polish State
    IPDONE INTEGER,				--Item num in Finished State
    IPTS TEXT,					--Item state time stamp

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Item Historical State
CREATE TABLE IF NOT EXISTS IHS (

    IHSID INTEGER PRIMARY KEY AUTOINCREMENT,	--Item Historical State ID
    IPID INTEGER,				--Item State ID
    ITEMID INTEGER,				--Item ID
    IHSCUT INTEGER,				--Item num in Cut State
    IHSGRND INTEGER,				--Item num in Grind State
    IHSWASH INTEGER,				--Item num in Wash State
    IHSFOIL INTEGER,				--Item num in Foil State
    IHSSLDR INTEGER,				--Item num in Solder State
    IHSPOLISH INTEGER,				--Item num in Polish State
    IHSDONE INTEGER,				--Item num in Finished State
    IHSTS TEXT,					--Item state time stamp

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (IPID) REFERENCES ICC(IPID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Item State Hours Taken
CREATE TABLE IF NOT EXISTS ITH (

    ITHID INTEGER PRIMARY KEY AUTOINCREMENT,	--Item Time Taken ID
    ITEMID INTEGER,				--Item ID
    IPCUT NUMERIC,				--Item Cut Time
    IPGRND NUMERIC,				--Item Grind Time
    IPWASH NUMERIC,				--Item Wash Time
    IPFOIL NUMERIC,				--Item Foil Time
    IPSLDR NUMERIC,				--Item Solder Time
    IPPOLISH NUMERIC,				--Item Polish Time
    IPTS TEXT,

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE

);

--Item Sale Transactions Date
CREATE TABLE IF NOT EXISTS ITMSALE (

    SALEID INTEGER PRIMARY KEY AUTOINCREMENT, 	--Sale ID
    ITEMID INTEGER,                           	--Item ID
    SUNITS INTEGER,                           	--Units Sold
    SDATE TEXT,                               	--Sale Date
    VENUEID INTEGER,                          	--Venue ID Sold at

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (VENUEID) REFERENCES VENUE(VENUEID) ON DELETE RESTRICT ON UPDATE CASCADE

);

--Daily Sales Report
CREATE TABLE IF NOT EXISTS TIMESALE (
    TSALEID INTEGER PRIMARY KEY AUTOINCREMENT, 	--Time Sale ID
    TSTIME TEXT,                              	--Hour Sales Occured
    TSUNITS INTEGER,                          	--Units Sold
    TSDATE TEXT,                              	--Date Sold
    VENUEID INTEGER,                          	--Venue ID Sold at

    FOREIGN KEY (VENUEID) REFERENCES VENUE(VENUEID) ON DELETE RESTRICT ON UPDATE CASCADE
);


--Glass Inventory
CREATE TABLE IF NOT EXISTS GLSINV (
    GLSTRNID INTEGER PRIMARY KEY AUTOINCREMENT, --Glass Inventory ID
    GLASSID INTEGER,				--Glass ID
    GLSSTOCK INTEGER,				--Glass current Stock
    TS TEXT,					--Glass Time Stamp

    FOREIGN KEY (GLASSID) REFERENCES GSI(GLASSID) ON DELETE SET NULL ON UPDATE CASCADE
);

--Misc Inventory
CREATE TABLE IF NOT EXISTS MSIINV (
    MSITRNID INTEGER PRIMARY KEY AUTOINCREMENT,	--Misc Inventory ID
    MSIID INTEGER,				--Misc ID
    MSISTOCK INTEGER,				--Misc current Stock
    TS TEXT,					--Time Stamp

    FOREIGN KEY (MSIID) REFERENCES MSI(MSIID) ON DELETE SET NULL ON UPDATE CASCADE
);

--Item Inventory
CREATE TABLE IF NOT EXISTS ITMINV (
    ITMTRNID INTEGER PRIMARY KEY AUTOINCREMENT,	--Item Inventory ID
    ITEMID INTEGER,				--Item ID
    ITMSTOCK INTEGER,				--Item current Stock
    TS TEXT,					--Time Stamp

    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE SET NULL ON UPDATE CASCADE
);

