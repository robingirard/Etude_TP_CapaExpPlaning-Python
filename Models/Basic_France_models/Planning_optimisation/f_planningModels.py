#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu May 14 07:51:58 2020

@author: robin.girard
"""
from __future__ import division

from pyomo.core import *
from pyomo.opt import SolverFactory

from EnergyAlternativesPlanning.f_model_definition import *
from EnergyAlternativesPlanning.f_model_cost_functions import *
from EnergyAlternativesPlanning.f_model_planning_constraints import *
from EnergyAlternativesPlanning.f_model_operation_constraints import *


def GetElectricSystemModel_PlanningSingleNode(Parameters):
    """
    This function creates the pyomo model and initlize the Parameters and (pyomo) Set values
    :param Parameters is a dictionnary with different panda tables :
        - areaConsumption: panda table with consumption
        - availabilityFactor: panda table
        - TechParameters : panda tables indexed by TECHNOLOGIES with eco and tech parameters
    """

    # isAbstract=False
    Parameters["availabilityFactor"].isna().sum()

    ### Cleaning
    availabilityFactor=Parameters["availabilityFactor"].fillna(method='pad');
    areaConsumption=Parameters["areaConsumption"].fillna(method='pad');
    TechParameters = Parameters["TechParameters"]

    ### obtaining dimensions values
    TECHNOLOGIES = set(TechParameters.index.get_level_values('TECHNOLOGIES').unique())
    Date = set(areaConsumption.index.get_level_values('Date').unique())
    Date_list = areaConsumption.index.get_level_values('Date').unique()

    model = ConcreteModel()

    ###############
    # Sets       ##
    ###############
    model.TECHNOLOGIES = Set(initialize=TECHNOLOGIES, ordered=False)
    model.Date = Set(initialize=Date, ordered=False)
    model.Date_TECHNOLOGIES = model.Date * model.TECHNOLOGIES

    # Subset of Simple only required if ramp constraint
    model.Date_MinusOne = Set(initialize=Date_list[: len(Date) - 1], ordered=False)
    model.Date_MinusThree = Set(initialize=Date_list[: len(Date) - 3], ordered=False)

    ###############
    # Parameters ##
    ###############

    model.areaConsumption = Param(model.Date, mutable=True,
                                  initialize=areaConsumption.loc[:, "areaConsumption"].squeeze().to_dict(), domain=Any)
    model.availabilityFactor = Param(model.Date_TECHNOLOGIES, domain=PercentFraction, default=1,
                                     initialize=availabilityFactor.loc[:, "availabilityFactor"].squeeze().to_dict())

    # with test of existing columns on TechParameters
    for COLNAME in Parameters["TechParameters"]:
        if COLNAME not in ["TECHNOLOGIES", "AREAS"]:  ### each column in TechParameters will be a parameter
            exec("model." + COLNAME + " =          Param(model.TECHNOLOGIES, domain=NonNegativeReals,default=0," +
                 "initialize=Parameters[\"TechParameters\"]." + COLNAME + ".squeeze().to_dict())")

    ################
    # Variables    #
    ################

    model.energy = Var(model.Date, model.TECHNOLOGIES,
                       domain=NonNegativeReals)  ### Energy produced by a production mean at time t
    model.energyCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacityCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacity = Var(model.TECHNOLOGIES,
                         domain=NonNegativeReals)  ### Energy produced by a production mean at time t

    model.dual = Suffix(direction=Suffix.IMPORT)
    model.rc = Suffix(direction=Suffix.IMPORT)
    model.slack = Suffix(direction=Suffix.IMPORT)

    ########################
    # Objective Function   #
    ########################

    def ObjectiveFunction_rule(model):  # OBJ
        return sum(model.energyCosts[tech] + model.capacityCosts[tech] for tech in model.TECHNOLOGIES)

    model.OBJ = Objective(rule=ObjectiveFunction_rule, sense=minimize)

    #################
    # Constraints   #
    #################

    # energyCosts definition Constraints
    def energyCostsDef_rule(model,
                            tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.energyCost[tech]  # /10**6 ;
        return sum(temp * model.energy[t, tech] for t in model.Date) == model.energyCosts[tech]

    model.energyCostsCtr = Constraint(model.TECHNOLOGIES, rule=energyCostsDef_rule)

    # capacityCosts definition Constraints
    def capacityCostsDef_rule(model,
                              tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.capacityCosts[tech]  # /10**6 ;
        return model.capacityCost[tech] * model.capacity[tech] == model.capacityCosts[tech]
        # return model.capacityCost[tech] * len(model.Date) / 8760 * model.capacity[tech] / 10 ** 6 == model.capacityCosts[tech]

    model.capacityCostsCtr = Constraint(model.TECHNOLOGIES, rule=capacityCostsDef_rule)

    #set_Operation_Constraints_CapacityCtr
    # contrainte de stock annuel

    # contrainte d'equilibre offre demande
    def energyCtr_rule(model, t):  # INEQ forall t
        return sum(model.energy[t, tech] for tech in model.TECHNOLOGIES) == model.areaConsumption[t]

    model.energyCtr = Constraint(model.Date, rule=energyCtr_rule)

    if "maxCapacity" in TechParameters:
        def maxCapacity_rule(model, tech):  # INEQ forall t, tech
            if model.maxCapacity[tech] > 0:
                return model.maxCapacity[tech] >= model.capacity[tech]
            else:
                return Constraint.Skip

        model.maxCapacityCtr = Constraint(model.TECHNOLOGIES, rule=maxCapacity_rule)

    if "minCapacity" in TechParameters:
        def minCapacity_rule(model, tech):  # INEQ forall t, tech
            if model.minCapacity[tech] > 0:
                return model.minCapacity[tech] <= model.capacity[tech]
            else:
                return Constraint.Skip

        model.minCapacityCtr = Constraint(model.TECHNOLOGIES, rule=minCapacity_rule)

    model=set_Operation_Constraints_stockCtr(model)
    model=set_Operation_Constraints_Ramp(model)

    return model;


def GetElectricSystemModel_PlanningSingleNode_withStorage(Parameters):
    """
    This function creates the pyomo model and initlize the Parameters and (pyomo) Set values
    :param Parameters is a dictionnary with different panda tables :
        - areaConsumption: panda table with consumption
        - availabilityFactor: panda table
        - TechParameters : panda tables indexed by TECHNOLOGIES with eco and tech parameters
        - StorageParameters : panda tables indexed by STOCK_TECHNO with eco and tech parameters
    :return: a dictionary with model : pyomo model without storage, storage : storage infos
    """

    Parameters["availabilityFactor"].isna().sum()

    ### Cleaning
    availabilityFactor=Parameters["availabilityFactor"].fillna(method='pad');
    areaConsumption=Parameters["areaConsumption"].fillna(method='pad');
    TechParameters=Parameters["TechParameters"]
    StorageParameters=Parameters["StorageParameters"]

    ### obtaining dimensions values
    TECHNOLOGIES = set(TechParameters.index.get_level_values('TECHNOLOGIES').unique())
    STOCK_TECHNO = set(StorageParameters.index.get_level_values('STOCK_TECHNO').unique())
    Date = set(areaConsumption.index.get_level_values('Date').unique())
    Date_list = areaConsumption.index.get_level_values('Date').unique()

    #####################
    #    Pyomo model    #
    #####################
    model = ConcreteModel()

    ###############
    # Sets       ##
    ###############
    model.TECHNOLOGIES = Set(initialize=TECHNOLOGIES, ordered=False)
    model.STOCK_TECHNO = Set(initialize=STOCK_TECHNO, ordered=False)
    model.Date = Set(initialize=Date, ordered=False)
    model.Date_TECHNOLOGIES = model.Date * model.TECHNOLOGIES

    # Subset of Simple only required if ramp constraint
    model.Date_MinusOne = Set(initialize=Date_list[: len(Date) - 1], ordered=False)
    model.Date_MinusThree = Set(initialize=Date_list[: len(Date) - 3], ordered=False)

    ###############
    # Parameters ##
    ###############

    model.areaConsumption = Param(model.Date, mutable=True,
                                  initialize=areaConsumption.loc[:, "areaConsumption"].squeeze().to_dict(), domain=Any)
    model.availabilityFactor = Param(model.Date_TECHNOLOGIES, domain=PercentFraction, default=1,
                                     initialize=availabilityFactor.loc[:, "availabilityFactor"].squeeze().to_dict())

    # with test of existing columns on TechParameters
    for COLNAME in TechParameters:
        if COLNAME not in ["TECHNOLOGIES", "AREAS"]:  ### each column in TechParameters will be a parameter
            exec("model." + COLNAME + " =          Param(model.TECHNOLOGIES, domain=NonNegativeReals,default=0," +
                 "initialize=TechParameters." + COLNAME + ".squeeze().to_dict())")

    for COLNAME in StorageParameters:
        if COLNAME not in ["STOCK_TECHNO", "AREAS"]:  ### each column in StorageParameters will be a parameter
            exec("model." + COLNAME + " =Param(model.STOCK_TECHNO,domain=NonNegativeReals,default=0," +
                 "initialize=StorageParameters." + COLNAME + ".squeeze().to_dict())")
    ## manière générique d'écrire pour toutes les colomnes COL de TechParameters quelque chose comme
    # model.COLNAME =          Param(model.TECHNOLOGIES, domain=NonNegativeReals,default=0,
    #                                  initialize=TechParameters.set_index([ "TECHNOLOGIES"]).COLNAME.squeeze().to_dict())

    ################
    # Variables    #
    ################

    ###Production means :
    model.energy = Var(model.Date, model.TECHNOLOGIES,
                       domain=NonNegativeReals)  ### Energy produced by a production mean at time t
    model.energyCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacityCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacity = Var(model.TECHNOLOGIES,domain=NonNegativeReals)  ### Energy produced by a production mean at time t

    ###Storage means :
    model.storageIn = Var(model.Date, model.STOCK_TECHNO,domain=NonNegativeReals)  ### Energy stored in a storage mean at time t
    model.storageOut = Var(model.Date, model.STOCK_TECHNO,domain=NonNegativeReals)  ### Energy taken out of a storage mean at time t
    model.stockLevel = Var(model.Date, model.STOCK_TECHNO,domain=NonNegativeReals)  ### level of the energy stock in a storage mean at time t
    model.storageCosts = Var(model.STOCK_TECHNO)  ### Cost of storage for a storage mean, explicitely defined by definition storageCostsDef
    model.Cmax = Var(model.STOCK_TECHNO)  # Maximum capacity of a storage mean
    model.Pmax = Var(model.STOCK_TECHNO)  # Maximum flow of energy in/out of a storage mean
    model.stockLevel_ini=Var(model.STOCK_TECHNO,domain=NonNegativeReals)

    ### Other :
    model.dual = Suffix(direction=Suffix.IMPORT)
    model.rc = Suffix(direction=Suffix.IMPORT)
    model.slack = Suffix(direction=Suffix.IMPORT)

    ########################
    # Objective Function   #
    ########################

    def ObjectiveFunction_rule(model):  # OBJ
        return sum(model.energyCosts[tech] + model.capacityCosts[tech] for tech in model.TECHNOLOGIES) + sum(
            model.storageCosts[s_tech] for s_tech in STOCK_TECHNO)

    model.OBJ = Objective(rule=ObjectiveFunction_rule, sense=minimize)

    #################
    # Constraints   #
    #################

    # energyCosts definition Constraints
    def energyCostsDef_rule(model,
                            tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.energyCost[tech]  # /10**6 ;
        return sum(temp * model.energy[t, tech] for t in model.Date) == model.energyCosts[tech]

    model.energyCostsCtr = Constraint(model.TECHNOLOGIES, rule=energyCostsDef_rule)

    # capacityCosts definition Constraints
    def capacityCostsDef_rule(model,
                              tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.capacityCosts[tech]  # /10**6 ;
        return model.capacityCost[tech] * model.capacity[tech] == model.capacityCosts[tech]
        # return model.capacityCost[tech] * len(model.Date) / 8760 * model.capacity[tech] / 10 ** 6 == model.capacityCosts[tech]

    model.capacityCostsCtr = Constraint(model.TECHNOLOGIES, rule=capacityCostsDef_rule)

    def storageCostsDef_rule(model,
                             s_tech):  # EQ forall s_tech in STOCK_TECHNO storageCosts=storageCost[s_tech]*Cmax[s_tech] / 1E6;
        return model.storageCost[s_tech] * model.Cmax[s_tech] == model.storageCosts[s_tech]

    model.storageCostsCtr = Constraint(model.STOCK_TECHNO, rule=storageCostsDef_rule)

    model = set_Operation_Constraints_CapacityCtr(model)#energy <= capacity * availabilityFactor

    # Storage max capacity constraint
    def storageCapacity_rule(model, s_tech):  # INEQ forall s_tech
        return model.Cmax[s_tech] <= model.c_max[s_tech]

    model.storageCapacityCtr = Constraint(model.STOCK_TECHNO, rule=storageCapacity_rule)

    # Storage max power constraint
    def storagePower_rule(model, s_tech):  # INEQ forall s_tech
        return model.Pmax[s_tech] <= model.p_max[s_tech]

    model.storagePowerCtr = Constraint(model.STOCK_TECHNO, rule=storagePower_rule)



    # contrainte d'equilibre offre demande
    # Date x TECHNOLOGIES
    def energyCtr_rule(model, t):  # INEQ forall t
        return sum(model.energy[t, tech] for tech in model.TECHNOLOGIES) + sum(
            model.storageOut[t, s_tech] - model.storageIn[t, s_tech] for s_tech in model.STOCK_TECHNO) == \
               model.areaConsumption[t]
    model.energyCtr = Constraint(model.Date, rule=energyCtr_rule)

    model = set_Planning_Constraints_maxCapacityCtr(model) #  model.maxCapacity[tech] >= model.capacity[tech]
    model = set_Planning_Constraints_minCapacityCtr(model) # model.minCapacity[tech] <= model.capacity[tech]

    # contraintes de stock puissance
    model=set_Operation_Constraints_Storage(model)
    model=set_Operation_Constraints_stockCtr(model)
    model=set_Operation_Constraints_Ramp(model)

    return model;

def Model_SingleNode_online_flex(Parameters):
    """
    This function takes storage characteristics, system characteristics and optimise operation Set values
    :param areaConsumption: panda table with consumption
    :param availabilityFactor: panda table
    :param to_flexible_consumption: dictionary with additional consumption name as key and consumption to make
    flexible as data
    :param isAbstract: boolean true is the model should be abstract. ConcreteModel otherwise
    :param StorageParameters is a dictionary with p_max (maximal power), c_max (energy capacity in the storage, maximal
    energy),
    efficiency_in (input efficiency of storage),
    efficiency_out (output efficiency of storage).
    :return: a dictionary with model : pyomo model without storage, storage : storage infos
    """
    # isAbstract=False

    to_flexible_consumption=Parameters["to_flexible_consumption"]
    ### Cleaning
    availabilityFactor = Parameters["availabilityFactor"].fillna(method='pad');
    areaConsumption = Parameters["areaConsumption"].fillna(method='pad');
    TechParameters = Parameters["TechParameters"]
    StorageParameters= Parameters["StorageParameters"]
    ConsoParameters=Parameters["ConsoParameters"]
    ### obtaining dimensions values
    TECHNOLOGIES = set(Parameters["TechParameters"].index.get_level_values('TECHNOLOGIES').unique())
    STOCK_TECHNO = set(Parameters["StorageParameters"].index.get_level_values('STOCK_TECHNO').unique())
    Date = set(areaConsumption.index.get_level_values('Date').unique())
    Date_list = areaConsumption.index.get_level_values('Date').unique()
    FLEX_CONSUM= set(ConsoParameters.index.get_level_values('FLEX_CONSUM').unique())

    #####################
    #    Pyomo model    #
    #####################
    model = ConcreteModel()

        ###############
    # Sets       ##
    ###############
    model.TECHNOLOGIES = Set(initialize=TECHNOLOGIES, ordered=False)
    model.STOCK_TECHNO = Set(initialize=STOCK_TECHNO, ordered=False)
    model.Date = Set(initialize=Date, ordered=False)
    model.Date_TECHNOLOGIES = model.Date * model.TECHNOLOGIES
    model.FLEX_CONSUM= Set(initialize=FLEX_CONSUM,ordered=False)
    model.Date_FLEX_CONSUM = model.Date * model.FLEX_CONSUM

    # Subset of Simple only required if ramp constraint
    model.Date_MinusOne = Set(initialize=Date_list[: len(Date) - 1], ordered=False)
    model.Date_MinusThree = Set(initialize=Date_list[: len(Date) - 3], ordered=False)

    model.WEEK_Date=Set(initialize=pd.Int64Index(Date_list.isocalendar().week).unique())


    ###############
    # Parameters ##
    ###############

    model.areaConsumption = Param(model.Date, mutable=True,
                                  initialize=areaConsumption.loc[:, "areaConsumption"].squeeze().to_dict(), domain=Any)
    model.availabilityFactor = Param(model.Date_TECHNOLOGIES, domain=PercentFraction, default=1,
                                     initialize=availabilityFactor.loc[:, "availabilityFactor"].squeeze().to_dict())
    model.to_flex_consumption = Param(model.Date_FLEX_CONSUM, domain=NonNegativeReals, default=1,
                                     initialize=to_flexible_consumption.loc[:, "to_flex_consumption"].squeeze().to_dict())
    # with test of existing columns on TechParameters
    for COLNAME in TechParameters:
        if COLNAME not in ["TECHNOLOGIES", "AREAS"]:  ### each column in TechParameters will be a parameter
            exec("model." + COLNAME + " =          Param(model.TECHNOLOGIES, mutable=False, domain=NonNegativeReals,default=0," +
                 "initialize=TechParameters." + COLNAME + ".squeeze().to_dict())")

    for COLNAME in StorageParameters:
        if COLNAME not in ["STOCK_TECHNO", "AREAS"]:  ### each column in StorageParameters will be a parameter
            exec("model." + COLNAME + " =Param(model.STOCK_TECHNO,mutable=False, domain=NonNegativeReals,default=0," +
                 "initialize=StorageParameters." + COLNAME + ".squeeze().to_dict())")


    if "to_flex_consumption" not in ConsoParameters:
        ConsoParameters_=ConsoParameters.join(to_flexible_consumption.groupby("FLEX_CONSUM").max().rename(columns={"to_flex_consumption" : "max_power"}))
    else:
        ConsoParameters_=ConsoParameters.rename(columns={"to_flex_consumption" : "max_power"})

    for COLNAME in ConsoParameters_:
        if COLNAME not in ["FLEX_CONSUM", "AREAS"]:  ### each column in StorageParameters will be a parameter
            #print(COLNAME)
            exec("model." + COLNAME + " =Param(model.FLEX_CONSUM,mutable=False,within=Any, default=0," +
                 "initialize=ConsoParameters_." + COLNAME + ".squeeze().to_dict())")

    ## manière générique d'écrire pour toutes les colomnes COL de TechParameters quelque chose comme
    # model.COLNAME =          Param(model.TECHNOLOGIES, domain=NonNegativeReals,default=0,
    #                                  initialize=TechParameters.set_index([ "TECHNOLOGIES"]).COLNAME.squeeze().to_dict())

    ################
    # Variables    #
    ################

    ###Consumption
    model.total_consumption=Var(model.Date,domain=NonNegativeReals) #variable de calcul intermediaire
    model.flex_consumption=Var(model.Date*model.FLEX_CONSUM,domain=NonNegativeReals) #flexible consumption variable
    model.increased_max_power=Var(model.FLEX_CONSUM,domain=NonNegativeReals) #flexible consumption maximum power
    model.consumption_power_cost=Var(model.FLEX_CONSUM,domain=NonNegativeReals)

    ### Flexibility variable
    model.flex = Var(model.Date * model.FLEX_CONSUM, domain=Reals)
    ###Production means :
    model.energy = Var(model.Date, model.TECHNOLOGIES,
                       domain=NonNegativeReals)  ### Energy produced by a production mean at time t
    model.energyCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacityCosts = Var(
        model.TECHNOLOGIES)  ### Cost of energy for a production mean, explicitely defined by definition energyCostsDef
    model.capacity = Var(model.TECHNOLOGIES,
                         domain=NonNegativeReals)  ### Energy produced by a production mean at time t

    ###Storage means :
    model.storageIn = Var(model.Date, model.STOCK_TECHNO,
                          domain=NonNegativeReals)  ### Energy stored in a storage mean at time t
    model.storageOut = Var(model.Date, model.STOCK_TECHNO,
                           domain=NonNegativeReals)  ### Energy taken out of a storage mean at time t
    model.stockLevel = Var(model.Date, model.STOCK_TECHNO,
                           domain=NonNegativeReals)  ### level of the energy stock in a storage mean at time t
    model.storageCosts = Var(
        model.STOCK_TECHNO)  ### Cost of storage for a storage mean, explicitely defined by definition storageCostsDef
    model.Cmax = Var(model.STOCK_TECHNO)  # Maximum capacity of a storage mean
    model.Pmax = Var(model.STOCK_TECHNO)  # Maximum flow of energy in/out of a storage mean

    ### Other :
    model.dual = Suffix(direction=Suffix.IMPORT)
    model.rc = Suffix(direction=Suffix.IMPORT)
    model.slack = Suffix(direction=Suffix.IMPORT)

    ########################
    # Objective Function   #
    ########################

    def ObjectiveFunction_rule(model):  # OBJ
        return sum(model.energyCosts[tech] + model.capacityCosts[tech] for tech in model.TECHNOLOGIES) + sum(
            model.storageCosts[s_tech] for s_tech in STOCK_TECHNO) + sum(model.consumption_power_cost[name] for name\
                                                                         in model.FLEX_CONSUM)

    model.OBJ = Objective(rule=ObjectiveFunction_rule, sense=minimize)

    #################
    # Constraints   #
    #################
    # Total consumption constraint
    #LoadCost;flex_ratio;max_ratio
    def total_consumption_rule(model,t):
        return model.total_consumption[t]== model.areaConsumption[t] + sum(model.flex_consumption[t,name] for name in model.FLEX_CONSUM)
    model.total_consumptionCtr=Constraint(model.Date,rule=total_consumption_rule)

    # Online flexible consumption constraints
    def max_power_rule(model,conso_type,t):
        return model.max_power[conso_type]+model.increased_max_power[conso_type]>=model.flex_consumption[t,conso_type]
    model.max_power_ruleCtr=Constraint(model.FLEX_CONSUM,model.Date,rule=max_power_rule)

    #definition of demand investiement cost
    def consumption_power_cost_rule(model,conso_type):
        return model.consumption_power_cost[conso_type]==model.LoadCost[conso_type]*model.increased_max_power[conso_type]
    model.consumption_power_costCtr=Constraint(model.FLEX_CONSUM,rule=consumption_power_cost_rule)

    # consumption equality within the same week
    def consum_eq_week(model,t_week,conso_type):
        if model.flex_type[conso_type] == 'week':
            #Date_list=model.Date
            t_range = Date_list[Date_list.isocalendar().week == t_week]  # range((t_week-1)*7*24+1,(t_week)*7*24)
            return sum(model.flex_consumption[t, conso_type] for t in t_range) == sum(model.to_flex_consumption[t, conso_type] for t in t_range)
        else:
            return Constraint.Skip
    model.consum_eq_week_Ctr= Constraint(model.WEEK_Date,model.FLEX_CONSUM,rule=consum_eq_week)

    def consum_eq_year(model,t_week,conso_type):
        if model.flex_type[conso_type] == 'year':
            return sum(model.flex_consumption[t, conso_type] for t in model.Date) == sum(model.to_flex_consumption[t, conso_type] for t in model.Date)
        else:
            return Constraint.Skip
    model.consum_eq_year_Ctr= Constraint(model.WEEK_Date,model.FLEX_CONSUM,rule=consum_eq_year)

    def consum_flex_rule(model,t,conso_type):
        return model.flex_consumption[t,conso_type]==model.to_flex_consumption[t,conso_type]*(1-model.flex[t,conso_type])
    model.consum_flex_Ctr=Constraint(model.Date,model.FLEX_CONSUM,rule=consum_flex_rule)

    def flex_variation_sup_rule(model,t,conso_type):
        return model.flex[t,conso_type]<= model.flex_ratio[conso_type]
    model.flex_variation_sup_Ctr=Constraint(model.Date,model.FLEX_CONSUM, rule=flex_variation_sup_rule)

    def flex_variation_inf_rule(model,t,conso_type):
        return model.flex[t,conso_type]>= -model.flex_ratio[conso_type]
    model.flex_variation_inf_Ctr=Constraint(model.Date,model.FLEX_CONSUM,rule=flex_variation_inf_rule)


    # energyCosts definition Constraints
    def energyCostsDef_rule(model,
                            tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.energyCost[tech]  # /10**6 ;
        return sum(temp * model.energy[t, tech] for t in model.Date) == model.energyCosts[tech]

    model.energyCostsCtr = Constraint(model.TECHNOLOGIES, rule=energyCostsDef_rule)

    # capacityCosts definition Constraints
    def capacityCostsDef_rule(model,
                              tech):  # EQ forall tech in TECHNOLOGIES   energyCosts  = sum{t in Date} energyCost[tech]*energy[t,tech] / 1E6;
        temp = model.capacityCosts[tech]  # /10**6 ;
        return model.capacityCost[tech] * model.capacity[tech] == model.capacityCosts[tech]
        # return model.capacityCost[tech] * len(model.Date) / 8760 * model.capacity[tech] / 10 ** 6 == model.capacityCosts[tech]

    model.capacityCostsCtr = Constraint(model.TECHNOLOGIES, rule=capacityCostsDef_rule)

    def storageCostsDef_rule(model,
                             s_tech):  # EQ forall s_tech in STOCK_TECHNO storageCosts=storageCost[s_tech]*Cmax[s_tech] / 1E6;
        return model.storageCost[s_tech] * model.Cmax[s_tech] == model.storageCosts[s_tech]

    model.storageCostsCtr = Constraint(model.STOCK_TECHNO, rule=storageCostsDef_rule)

    model = set_Operation_Constraints_CapacityCtr(model)#energy <= capacity * availabilityFactor

    # Storage max capacity constraint
    def storageCapacity_rule(model, s_tech):  # INEQ forall s_tech
        return model.Cmax[s_tech] <= model.c_max[s_tech]
    model.storageCapacityCtr = Constraint(model.STOCK_TECHNO, rule=storageCapacity_rule)

    # Storage max power constraint
    def storagePower_rule(model, s_tech):  # INEQ forall s_tech
        return model.Pmax[s_tech] <= model.p_max[s_tech]
    model.storagePowerCtr = Constraint(model.STOCK_TECHNO, rule=storagePower_rule)


    # contrainte d'equilibre offre demande
    def energyCtr_rule(model, t):  # INEQ forall t
        return sum(model.energy[t, tech] for tech in model.TECHNOLOGIES) + sum(
            model.storageOut[t, s_tech] - model.storageIn[t, s_tech] for s_tech in model.STOCK_TECHNO) >= \
               model.total_consumption[t]

    model.energyCtr = Constraint(model.Date, rule=energyCtr_rule)

    model = set_Planning_Constraints_maxCapacityCtr(model) #  model.maxCapacity[tech] >= model.capacity[tech]
    model = set_Planning_Constraints_minCapacityCtr(model) # model.minCapacity[tech] <= model.capacity[tech]

    model = set_Operation_Constraints_Storage(model)
    model = set_Operation_Constraints_stockCtr(model)
    model = set_Operation_Constraints_Ramp(model)

    return model;



